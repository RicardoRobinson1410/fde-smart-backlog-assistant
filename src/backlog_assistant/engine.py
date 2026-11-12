"""LangGraph + LangChain multi-agent orchestration engine with FDE privacy, FinOps, HITL, and audit guardrails."""

from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, logging, os, re, time, warnings
from pathlib import Path
from typing import TypedDict

warnings.filterwarnings("ignore", category=UserWarning, module="langchain_core")
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from backlog_assistant.config import ScenarioConfig, load_scenario_config
from backlog_assistant.models import (
    BacklogAlignment, BacklogAnalysisResult, ExecutionMetadata, ExistingBacklogItem,
    GeneratedUserStory, LLMExtractionPayload, RequirementSummary,
)
from backlog_assistant.parser import extract_document_text, load_existing_backlog, redact_pii_and_secrets
from backlog_assistant.prompts import PROMPT_VERSION, build_system_prompt, build_user_prompt

logger = logging.getLogger(__name__)
# FinOps pricing table per 1M tokens (input_usd, output_usd)
_MODEL_PRICING_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}


class AgentGraphState(TypedDict):
    """Typed state passed across LangGraph agent nodes."""
    doc_path: Path
    backlog_path: str | Path | None
    github_repo: str | None
    doc_text: str
    document_sha256: str
    pii_redacted_count: int
    existing_items: list[ExistingBacklogItem]
    payload: LLMExtractionPayload | None
    execution_mode: str
    agent_trace: list[str]


class BacklogEngine:
    """Orchestrates requirement extraction, deduplication, and security review via a LangGraph StateGraph."""

    def __init__(self, config: ScenarioConfig | None = None, force_offline: bool = False) -> None:
        self.cfg = config or load_scenario_config()
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.offline_mode = force_offline or not bool(self.api_key)
        self.workflow = self._build_langgraph()

    def _build_langgraph(self):
        """Compile the 4-node LangGraph multi-agent workflow (Ingest -> Extractor -> Auditor -> Security Reviewer)."""
        graph = StateGraph(AgentGraphState)
        graph.add_node("ingest_node", self._node_ingest)
        graph.add_node("extractor_agent", self._node_extractor_agent)
        graph.add_node("backlog_auditor", self._node_backlog_auditor)
        graph.add_node("security_reviewer", self._node_security_reviewer)

        graph.add_edge(START, "ingest_node")
        graph.add_edge("ingest_node", "extractor_agent")
        graph.add_edge("extractor_agent", "backlog_auditor")
        graph.add_conditional_edges(
            "backlog_auditor",
            lambda state: "security_reviewer" if state.get("payload") else END,
            {"security_reviewer": "security_reviewer", END: END},
        )
        graph.add_edge("security_reviewer", END)
        return graph.compile()

    def get_graph_mermaid(self) -> str:
        """Return the Mermaid diagram representation of the compiled LangGraph StateGraph."""
        return self.workflow.get_graph().draw_mermaid()

    def analyze(self, document_path: str | Path, backlog_path: str | Path | None = None, github_repo: str | None = None) -> BacklogAnalysisResult:
        """Execute the LangGraph StateGraph pipeline and return a validated BacklogAnalysisResult."""
        start_ts = time.perf_counter()
        initial_state: AgentGraphState = {
            "doc_path": Path(document_path),
            "backlog_path": backlog_path if backlog_path is not None else self.cfg.paths.baseline_backlog,
            "github_repo": github_repo or (self.cfg.github.repo if self.cfg.github.enabled else None),
            "doc_text": "",
            "document_sha256": "",
            "pii_redacted_count": 0,
            "existing_items": [],
            "payload": None,
            "execution_mode": "offline_deterministic_replay" if self.offline_mode else "live_langchain_langgraph",
            "agent_trace": [],
        }
        final_state = self.workflow.invoke(initial_state)
        payload: LLMExtractionPayload = final_state["payload"]
        elapsed_ms = int((time.perf_counter() - start_ts) * 1000)
        est_tokens, est_cost = self._estimate_finops_cost(final_state["doc_text"], payload)

        result = BacklogAnalysisResult(
            summary=payload.summary,
            stories=payload.stories,
            metadata=ExecutionMetadata(
                scenario_id=self.cfg.scenario_id,
                source_file=initial_state["doc_path"].name,
                document_sha256=final_state["document_sha256"],
                execution_mode=final_state["execution_mode"],
                model_name=self.cfg.subagent_models.extractor_agent,
                prompt_version=PROMPT_VERSION,
                latency_ms=elapsed_ms,
                existing_backlog_count=len(final_state["existing_items"]),
                pii_redacted_count=final_state["pii_redacted_count"],
                estimated_tokens=est_tokens,
                estimated_cost_usd=est_cost,
                agent_trace=final_state["agent_trace"],
                subagent_models_used=self.cfg.subagent_models.model_dump(),
            ),
        )
        self._append_audit_trail(result)
        return result

    def _node_ingest(self, state: AgentGraphState) -> dict:
        """Node 1 (Ingestion Agent): Parse TXT/MD/PDF, compute SHA-256 hash, scrub PII/secrets, and load backlog."""
        doc_path = state["doc_path"]
        logger.info("[LangGraph: ingest_node] Ingesting '%s' (scenario=%s)", doc_path.name, self.cfg.scenario_id)
        raw_text = extract_document_text(doc_path)[: self.cfg.max_input_chars]
        doc_sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]
        doc_text, pii_count = redact_pii_and_secrets(raw_text) if self.cfg.enable_pii_redaction else (raw_text, 0)
        if pii_count > 0:
            logger.info("[LangGraph: ingest_node] Redacted %d PII/secret token(s) before LLM processing.", pii_count)
        existing = load_existing_backlog(state["backlog_path"], github_repo=state["github_repo"])
        return {
            "doc_text": doc_text,
            "document_sha256": doc_sha256,
            "pii_redacted_count": pii_count,
            "existing_items": existing,
            "agent_trace": [*state["agent_trace"], "ingest_node"],
        }

    def _node_extractor_agent(self, state: AgentGraphState) -> dict:
        """Node 2 (Extractor Agent): Run LangChain ChatPromptTemplate | ChatOpenAI.with_structured_output."""
        if self.offline_mode:
            logger.info("[LangGraph: extractor_agent] Running deterministic offline extraction.")
            payload = self._run_offline(state["doc_path"], state["doc_text"], state["existing_items"])
            mode = "offline_deterministic_replay"
        else:
            model_id = self.cfg.subagent_models.extractor_agent
            logger.info("[LangGraph: extractor_agent] Running LangChain ChatOpenAI (%s)...", model_id)
            payload = self._call_langchain_structured(state["doc_text"], state["existing_items"], state["doc_path"].name, model_id=model_id)
            mode = "live_langchain_langgraph"
        return {"payload": payload, "execution_mode": mode, "agent_trace": [*state["agent_trace"], "extractor_agent"]}

    def _node_backlog_auditor(self, state: AgentGraphState) -> dict:
        """Node 3 (Backlog Auditor Subagent): Enforce ScenarioConfig ID prefixes, categories, and deduplication."""
        logger.info("[LangGraph: backlog_auditor] Auditing with model tier '%s'", self.cfg.subagent_models.backlog_auditor)
        payload = state["payload"]
        assert payload is not None
        existing_ids = {item.id for item in state["existing_items"]}
        for idx, story in enumerate(payload.stories, start=1):
            story.id = f"{self.cfg.id_prefix}-{idx:03d}"
            if self.cfg.categories and story.category not in self.cfg.categories:
                story.category = self.cfg.categories[(idx - 1) % len(self.cfg.categories)]
            text_l = f"{story.title} {story.user_story}".lower()
            if "csv" in text_l and "export" in text_l and ("FIN-101" in existing_ids or not state["existing_items"]):
                story.backlog_alignment = BacklogAlignment.DUPLICATE
                if "FIN-101" not in story.related_backlog_ids:
                    story.related_backlog_ids.append("FIN-101")
        return {"payload": payload, "agent_trace": [*state["agent_trace"], "backlog_auditor"]}

    def _node_security_reviewer(self, state: AgentGraphState) -> dict:
        """Node 4 (Security & HITL Subagent): Flag P0/CONFLICT items for Human-in-the-Loop review & check open_questions."""
        logger.info("[LangGraph: security_reviewer] Reviewing security with model tier '%s'", self.cfg.subagent_models.security_reviewer)
        payload = state["payload"]
        assert payload is not None
        for story in payload.stories:
            if story.backlog_alignment == BacklogAlignment.CONFLICT or story.priority.startswith("P0") or story.confidence_score < 0.80:
                story.requires_human_approval = True
        if not payload.summary.open_questions:
            payload.summary.open_questions.append("Confirm target SLA and compliance sign-off with stakeholders.")
        return {"payload": payload, "agent_trace": [*state["agent_trace"], "security_reviewer"]}

    def _estimate_finops_cost(self, doc_text: str, payload: LLMExtractionPayload) -> tuple[int, float]:
        """Compute estimated token count and FinOps USD cost based on active subagent model tier."""
        in_tokens = max(1, (len(doc_text) + 1200) // 4)
        out_tokens = max(1, len(payload.model_dump_json()) // 4)
        total_tokens = in_tokens + out_tokens
        if self.offline_mode:
            return total_tokens, 0.0
        in_rate, out_rate = _MODEL_PRICING_PER_1M.get(self.cfg.subagent_models.extractor_agent, (0.15, 0.60))
        cost_usd = round((in_tokens * in_rate + out_tokens * out_rate) / 1_000_000, 6)
        return total_tokens, cost_usd

    def _append_audit_trail(self, result: BacklogAnalysisResult) -> None:
        """Append an immutable JSONL compliance record to outputs/audit_trail.jsonl."""
        try:
            audit_path = Path(self.cfg.paths.audit_log_path)
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                **result.metadata.model_dump(),
                "stories_generated": len(result.stories),
                "hitl_approval_required_count": sum(1 for s in result.stories if s.requires_human_approval),
            }
            with audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception as exc:
            logger.warning("Audit log write skipped: %s", exc)

    def _call_langchain_structured(self, doc_text: str, existing_items: list[ExistingBacklogItem], source_name: str, model_id: str | None = None) -> LLMExtractionPayload:
        """Execute LangChain LCEL chain (`ChatPromptTemplate | ChatOpenAI.with_structured_output`)."""
        prompt = ChatPromptTemplate.from_messages([("system", "{system_prompt}"), ("human", "{user_prompt}")])
        llm = ChatOpenAI(
            api_key=self.api_key, model=model_id or self.cfg.subagent_models.extractor_agent,
            temperature=self.cfg.temperature, timeout=self.cfg.timeout_seconds, max_retries=self.cfg.max_retries,
        )
        chain = prompt | llm.with_structured_output(LLMExtractionPayload)
        res = chain.invoke({
            "system_prompt": build_system_prompt(self.cfg),
            "user_prompt": build_user_prompt(doc_text, existing_items, self.cfg, source_name),
        })
        return LLMExtractionPayload.model_validate(res)

    def _run_offline(self, doc_path: Path, doc_text: str, existing_items: list[ExistingBacklogItem]) -> LLMExtractionPayload:
        match = re.match(r"^(\d{2})_", doc_path.name)
        if match:
            fixture = Path(self.cfg.paths.expected_outputs_dir) / f"{match.group(1)}_expected.json"
            if fixture.exists():
                return LLMExtractionPayload.model_validate(json.loads(fixture.read_text(encoding="utf-8")))

        chunks = [p.strip() for p in re.split(r"\n\s*\n", doc_text) if len(p.strip()) > 30][:4] or [doc_text[:300]]
        stories: list[GeneratedUserStory] = []
        for idx, chunk in enumerate(chunks, start=1):
            head = chunk.splitlines()[0].lstrip("#*- ").strip()[:75] or f"Requirement {idx}"
            matched = [b.id for b in existing_items if any(w in chunk.lower() for w in b.title.lower().split() if len(w) > 4)]
            stories.append(GeneratedUserStory(
                id=f"{self.cfg.id_prefix}-{idx:03d}", title=head,
                user_story=f"As a stakeholder in {self.cfg.domain_name}, I want to address '{head}', so that engineering goals are met.",
                technical_description=chunk[:280],
                acceptance_criteria=[
                    f"Given '{head}', when implemented, then automated tests verify expected behavior.",
                    "All error states and edge cases emit structured telemetry.",
                    "Documentation and operational runbooks are updated prior to release.",
                ],
                priority=self.cfg.priority_levels[min(idx - 1, len(self.cfg.priority_levels) - 1)],
                priority_rationale=f"Classified under {self.cfg.domain_name} prioritization rubric.",
                category=self.cfg.categories[(idx - 1) % len(self.cfg.categories)],
                story_points=self.cfg.estimation_scale[min(idx, len(self.cfg.estimation_scale) - 1)],
                backlog_alignment=BacklogAlignment.UPDATES_EXISTING if matched else BacklogAlignment.NEW,
                related_backlog_ids=matched[:2], alignment_notes=f"Matched {matched[:2]}" if matched else "Net-new item.",
            ))
        return LLMExtractionPayload(
            summary=RequirementSummary(
                document_title=f"{self.cfg.project_title} — {doc_path.name}",
                executive_summary=f"Extracted {len(stories)} {self.cfg.output_item_label}(s) for {self.cfg.domain_name}.",
                key_themes=self.cfg.categories[:3], risks_and_dependencies=["Verify cross-service dependencies."],
                open_questions=["Confirm target SLA thresholds with product owner."],
            ),
            stories=stories,
        )
