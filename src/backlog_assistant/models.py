"""Pydantic v2 domain models enforcing structured AI outputs, deduplication, and rubric guardrails."""

from __future__ import annotations
from enum import Enum
from typing import TYPE_CHECKING
from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from backlog_assistant.config import ScenarioConfig


class BacklogAlignment(str, Enum):
    NEW = "NEW"
    UPDATES_EXISTING = "UPDATES_EXISTING"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"


class ExistingBacklogItem(BaseModel):
    id: str
    title: str
    status: str = "Open"
    priority: str = "P2 - Medium"
    category: str = "Feature"
    summary: str


class RequirementSummary(BaseModel):
    document_title: str = Field(description="Inferred title or topic of the source document")
    executive_summary: str = Field(description="Concise 2-3 sentence synthesis of key engineering goals")
    key_themes: list[str] = Field(description="Primary technical themes identified in the input")
    risks_and_dependencies: list[str] = Field(description="Cross-team dependencies, security, or SLA risks")
    open_questions: list[str] = Field(description="Missing specifications to clarify instead of hallucinating")


class GeneratedUserStory(BaseModel):
    id: str = Field(description="Identifier using the configured prefix, e.g. STORY-001")
    title: str = Field(description="Short, actionable engineering title")
    user_story: str = Field(description="Formatted per scenario story_template (As a ..., I want ..., so that ...)")
    technical_description: str = Field(description="Implementation details, affected services, and constraints")
    acceptance_criteria: list[str] = Field(min_length=3, description="At least 3 testable acceptance criteria")
    priority: str = Field(description="Priority level from scenario priority_levels")
    priority_rationale: str = Field(description="Why this priority was assigned based on the scenario rubric")
    category: str = Field(description="Category from scenario categories")
    story_points: int = Field(description="Effort estimate from Fibonacci scale (1, 2, 3, 5, 8, 13)")
    backlog_alignment: BacklogAlignment = Field(description="NEW, UPDATES_EXISTING, DUPLICATE, or CONFLICT")
    related_backlog_ids: list[str] = Field(default_factory=list, description="IDs from existing backlog")
    alignment_notes: str = Field(default="", description="Explanation of overlap/update/conflict")
    confidence_score: float = Field(default=0.92, ge=0.0, le=1.0, description="AI extraction confidence (0.0 to 1.0)")
    requires_human_approval: bool = Field(
        default=False,
        description="True when item is P0-Critical, CONFLICT, or low confidence and requires HITL sign-off",
    )

    @field_validator("acceptance_criteria")
    @classmethod
    def ensure_non_empty_criteria(cls, v: list[str]) -> list[str]:
        cleaned = [item.strip() for item in v if item and item.strip()]
        if len(cleaned) < 3:
            raise ValueError("Each generated story must include at least 3 non-empty acceptance criteria.")
        return cleaned


class ExecutionMetadata(BaseModel):
    scenario_id: str
    source_file: str
    document_sha256: str = Field(default="", description="SHA-256 fingerprint of raw input for idempotency & audit")
    execution_mode: str
    model_name: str
    prompt_version: str
    latency_ms: int
    existing_backlog_count: int
    pii_redacted_count: int = Field(default=0, description="Count of PII/secret tokens masked prior to LLM call")
    estimated_tokens: int = Field(default=0, description="Estimated total input + output tokens consumed")
    estimated_cost_usd: float = Field(default=0.0, description="FinOps estimated API cost in USD")
    agent_trace: list[str] = Field(default_factory=list, description="Executed LangGraph multi-agent node trace")
    subagent_models_used: dict[str, str] = Field(default_factory=dict, description="Model assigned to each subagent for cost optimization")


class LLMExtractionPayload(BaseModel):
    summary: RequirementSummary
    stories: list[GeneratedUserStory]


class BacklogAnalysisResult(BaseModel):
    summary: RequirementSummary
    stories: list[GeneratedUserStory]
    metadata: ExecutionMetadata

    def to_markdown(self, cfg: ScenarioConfig | None = None) -> str:
        title = cfg.project_title if cfg else "Smart Backlog Assistant Report"
        label = cfg.output_item_label if cfg else "User Story"
        lines = [
            f"# {title}: `{self.summary.document_title}`",
            f"> **Mode**: `{self.metadata.execution_mode}` | **Model**: `{self.metadata.model_name}` | **Latency**: `{self.metadata.latency_ms} ms`",
            "", "## 1. Executive Summary", self.summary.executive_summary, "",
            "### Risks & Dependencies", *[f"- {r}" for r in self.summary.risks_and_dependencies], "",
            "### Open Questions (Anti-Hallucination Guardrail)", *[f"- [ ] {q}" for q in self.summary.open_questions], "",
            f"## 2. Generated {label}s ({len(self.stories)} total)",
        ]
        for s in self.stories:
            refs = f" (Refs: `{', '.join(s.related_backlog_ids)}`)" if s.related_backlog_ids else ""
            lines.extend([
                f"### [{s.id}] {s.title}",
                f"- **Alignment**: `{s.backlog_alignment.value}`{refs} — {s.alignment_notes}",
                f"- **Priority**: `{s.priority}` ({s.priority_rationale}) | **Category**: `{s.category}` | **Est**: `{s.story_points} pts`",
                f"- **{label}**: *{s.user_story}*",
                f"- **Technical Context**: {s.technical_description}",
                "- **Acceptance Criteria**:", *[f"  - [x] {ac}" for ac in s.acceptance_criteria], "",
            ])
        return "\n".join(lines)
