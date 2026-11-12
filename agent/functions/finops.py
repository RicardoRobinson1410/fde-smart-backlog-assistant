"""FinOps token pricing and audit logging helpers."""

from __future__ import annotations
from datetime import datetime, timezone
import json
import logging
from pathlib import Path

from backlog_assistant.config import ScenarioConfig
from backlog_assistant.models import BacklogAnalysisResult, LLMExtractionPayload

logger = logging.getLogger(__name__)

# FinOps pricing table per 1M tokens (input_usd, output_usd)
_MODEL_PRICING_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}


def estimate_finops_cost(
    doc_text: str,
    payload: LLMExtractionPayload,
    cfg: ScenarioConfig,
    offline_mode: bool,
) -> tuple[int, float]:
    """Compute estimated token count and FinOps USD cost based on active subagent model tier."""
    in_tokens = max(1, (len(doc_text) + 1200) // 4)
    out_tokens = max(1, len(payload.model_dump_json()) // 4)
    total_tokens = in_tokens + out_tokens
    if offline_mode:
        return total_tokens, 0.0
    in_rate, out_rate = _MODEL_PRICING_PER_1M.get(cfg.subagent_models.extractor_agent, (0.15, 0.60))
    cost_usd = round((in_tokens * in_rate + out_tokens * out_rate) / 1_000_000, 6)
    return total_tokens, cost_usd


def append_audit_trail(result: BacklogAnalysisResult, cfg: ScenarioConfig) -> None:
    """Append an immutable JSONL compliance record to outputs/audit_trail.jsonl."""
    try:
        audit_path = Path(cfg.paths.audit_log_path)
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
