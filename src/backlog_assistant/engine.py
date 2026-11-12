"""LangGraph multi-agent orchestration engine with FDE privacy, FinOps, HITL, and audit guardrails."""

from __future__ import annotations
import os
from pathlib import Path
import time

from langgraph.graph import END, START, StateGraph

from backlog_assistant.config import ScenarioConfig, load_scenario_config
from backlog_assistant.models import (
    BacklogAnalysisResult, ExecutionMetadata, LLMExtractionPayload,
)
from backlog_assistant.prompts import PROMPT_VERSION
from backlog_assistant.functions import (
    AgentGraphState,
    node_ingest,
    node_extractor_agent,
    node_backlog_auditor,
    node_security_reviewer,
    estimate_finops_cost,
    append_audit_trail,
)


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
        graph.add_node("ingest_node", lambda s: node_ingest(s, self.cfg))
        graph.add_node("extractor_agent", lambda s: node_extractor_agent(s, self.cfg, self.offline_mode, self.api_key))
        graph.add_node("backlog_auditor", lambda s: node_backlog_auditor(s, self.cfg))
        graph.add_node("security_reviewer", lambda s: node_security_reviewer(s, self.cfg))

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

    def analyze(self, document_path: str | Path, backlog_path: str | Path | None = None) -> BacklogAnalysisResult:
        """Execute the LangGraph StateGraph pipeline and return a validated BacklogAnalysisResult."""
        start_ts = time.perf_counter()
        initial_state: AgentGraphState = {
            "doc_path": Path(document_path),
            "backlog_path": backlog_path if backlog_path is not None else self.cfg.paths.baseline_backlog,
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
        est_tokens, est_cost = estimate_finops_cost(final_state["doc_text"], payload, self.cfg, self.offline_mode)

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
        append_audit_trail(result, self.cfg)
        return result
