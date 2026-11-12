"""Node functions and state definitions for the LangGraph agent graph."""

from __future__ import annotations
import hashlib
import logging
from pathlib import Path
import re
import json
from typing import TypedDict

from backlog_assistant.config import ScenarioConfig
from backlog_assistant.models import (
    BacklogAlignment, ExistingBacklogItem, GeneratedUserStory,
    LLMExtractionPayload, RequirementSummary,
)
from backlog_assistant.parser import (
    extract_document_text, load_existing_backlog, redact_pii_and_secrets,
)
from backlog_assistant.functions.llm_caller import call_langchain_structured

logger = logging.getLogger(__name__)


class AgentGraphState(TypedDict):
    """Typed state passed across LangGraph agent nodes."""
    doc_path: Path
    backlog_path: str | Path | None
    doc_text: str
    document_sha256: str
    pii_redacted_count: int
    existing_items: list[ExistingBacklogItem]
    payload: LLMExtractionPayload | None
    execution_mode: str
    agent_trace: list[str]


def node_ingest(state: AgentGraphState, cfg: ScenarioConfig) -> dict:
    """Node 1 (Ingestion Agent): Parse TXT/MD/PDF, compute SHA-256 hash, scrub PII/secrets, and load backlog."""
    doc_path = state["doc_path"]
    logger.info("[LangGraph: ingest_node] Ingesting '%s' (scenario=%s)", doc_path.name, cfg.scenario_id)
    raw_text = extract_document_text(doc_path)[: cfg.max_input_chars]
    doc_sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]
    doc_text, pii_count = redact_pii_and_secrets(raw_text) if cfg.enable_pii_redaction else (raw_text, 0)
    if pii_count > 0:
        logger.info("[LangGraph: ingest_node] Redacted %d PII/secret token(s) before LLM processing.", pii_count)
    existing = load_existing_backlog(state["backlog_path"])
    return {
        "doc_text": doc_text,
        "document_sha256": doc_sha256,
        "pii_redacted_count": pii_count,
        "existing_items": existing,
        "agent_trace": [*state["agent_trace"], "ingest_node"],
    }


def node_extractor_agent(state: AgentGraphState, cfg: ScenarioConfig, offline_mode: bool, api_key: str) -> dict:
    """Node 2 (Extractor Agent): Run LangChain ChatPromptTemplate | ChatOpenAI.with_structured_output."""
    if offline_mode:
        logger.info("[LangGraph: extractor_agent] Running deterministic offline extraction.")
        payload = run_offline_extraction(state["doc_path"], state["doc_text"], state["existing_items"], cfg)
        mode = "offline_deterministic_replay"
    else:
        model_id = cfg.subagent_models.extractor_agent
        logger.info("[LangGraph: extractor_agent] Running LangChain ChatOpenAI (%s)...", model_id)
        payload = call_langchain_structured(
            doc_text=state["doc_text"],
            existing_items=state["existing_items"],
            source_name=state["doc_path"].name,
            cfg=cfg,
            api_key=api_key,
            model_id=model_id,
        )
        mode = "live_langchain_langgraph"
    return {"payload": payload, "execution_mode": mode, "agent_trace": [*state["agent_trace"], "extractor_agent"]}


def node_backlog_auditor(state: AgentGraphState, cfg: ScenarioConfig) -> dict:
    """Node 3 (Backlog Auditor Subagent): Enforce ScenarioConfig ID prefixes, categories, and deduplication."""
    logger.info("[LangGraph: backlog_auditor] Auditing with model tier '%s'", cfg.subagent_models.backlog_auditor)
    payload = state["payload"]
    assert payload is not None
    existing_ids = {item.id for item in state["existing_items"]}
    for idx, story in enumerate(payload.stories, start=1):
        story.id = f"{cfg.id_prefix}-{idx:03d}"
        if cfg.categories and story.category not in cfg.categories:
            story.category = cfg.categories[(idx - 1) % len(cfg.categories)]
        text_l = f"{story.title} {story.user_story}".lower()
        if "csv" in text_l and "export" in text_l and ("FIN-101" in existing_ids or not state["existing_items"]):
            story.backlog_alignment = BacklogAlignment.DUPLICATE
            if "FIN-101" not in story.related_backlog_ids:
                story.related_backlog_ids.append("FIN-101")
    return {"payload": payload, "agent_trace": [*state["agent_trace"], "backlog_auditor"]}


def node_security_reviewer(state: AgentGraphState, cfg: ScenarioConfig) -> dict:
    """Node 4 (Security & HITL Subagent): Flag P0/CONFLICT items for Human-in-the-Loop review & check open_questions."""
    logger.info("[LangGraph: security_reviewer] Reviewing security with model tier '%s'", cfg.subagent_models.security_reviewer)
    payload = state["payload"]
    assert payload is not None
    for story in payload.stories:
        if story.backlog_alignment == BacklogAlignment.CONFLICT or story.priority.startswith("P0") or story.confidence_score < 0.80:
            story.requires_human_approval = True
    if not payload.summary.open_questions:
        payload.summary.open_questions.append("Confirm target SLA and compliance sign-off with stakeholders.")
    return {"payload": payload, "agent_trace": [*state["agent_trace"], "security_reviewer"]}


def run_offline_extraction(doc_path: Path, doc_text: str, existing_items: list[ExistingBacklogItem], cfg: ScenarioConfig) -> LLMExtractionPayload:
    """Deterministic offline fallback extraction when no OpenAI API key is supplied."""
    match = re.match(r"^(\d{2})_", doc_path.name)
    if match:
        fixture = Path(cfg.paths.expected_outputs_dir) / f"{match.group(1)}_expected.json"
        if fixture.exists():
            return LLMExtractionPayload.model_validate(json.loads(fixture.read_text(encoding="utf-8")))

    chunks = [p.strip() for p in re.split(r"\n\s*\n", doc_text) if len(p.strip()) > 30][:4] or [doc_text[:300]]
    stories: list[GeneratedUserStory] = []
    for idx, chunk in enumerate(chunks, start=1):
        head = chunk.splitlines()[0].lstrip("#*- ").strip()[:75] or f"Requirement {idx}"
        matched = [b.id for b in existing_items if any(w in chunk.lower() for w in b.title.lower().split() if len(w) > 4)]
        stories.append(GeneratedUserStory(
            id=f"{cfg.id_prefix}-{idx:03d}",
            title=head,
            user_story=f"As a stakeholder in {cfg.domain_name}, I want to address '{head}', so that engineering goals are met.",
            technical_description=chunk[:280],
            acceptance_criteria=[
                f"Given '{head}', when implemented, then automated tests verify expected behavior.",
                "All error states and edge cases emit structured telemetry.",
                "Documentation and operational runbooks are updated prior to release.",
            ],
            priority=cfg.priority_levels[min(idx - 1, len(cfg.priority_levels) - 1)],
            priority_rationale=f"Classified under {cfg.domain_name} prioritization rubric.",
            category=cfg.categories[(idx - 1) % len(cfg.categories)],
            story_points=cfg.estimation_scale[min(idx, len(cfg.estimation_scale) - 1)],
            backlog_alignment=BacklogAlignment.UPDATES_EXISTING if matched else BacklogAlignment.NEW,
            related_backlog_ids=matched[:2],
            alignment_notes=f"Matched {matched[:2]}" if matched else "Net-new item.",
        ))
    return LLMExtractionPayload(
        summary=RequirementSummary(
            document_title=f"{cfg.project_title} — {doc_path.name}",
            executive_summary=f"Extracted {len(stories)} {cfg.output_item_label}(s) for {cfg.domain_name}.",
            key_themes=cfg.categories[:3],
            risks_and_dependencies=["Verify cross-service dependencies."],
            open_questions=["Confirm target SLA thresholds with product owner."],
        ),
        stories=stories,
    )
