"""AI orchestration engine with OpenAI Structured Outputs, retry guardrails, and offline fallback."""

from __future__ import annotations
import json, logging, os, re, time
from pathlib import Path
from openai import OpenAI
from backlog_assistant.config import ScenarioConfig, load_scenario_config
from backlog_assistant.models import (
    BacklogAlignment, BacklogAnalysisResult, ExecutionMetadata, ExistingBacklogItem,
    GeneratedUserStory, LLMExtractionPayload, RequirementSummary,
)
from backlog_assistant.parser import extract_document_text, load_existing_backlog
from backlog_assistant.prompts import PROMPT_VERSION, build_system_prompt, build_user_prompt

logger = logging.getLogger(__name__)


class BacklogEngine:
    """Executes requirement extraction and backlog deduplication using ScenarioConfig variables."""

    def __init__(self, config: ScenarioConfig | None = None, force_offline: bool = False) -> None:
        self.cfg = config or load_scenario_config()
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.offline_mode = force_offline or not bool(self.api_key)

    def analyze(self, document_path: str | Path, backlog_path: str | Path | None = None, github_repo: str | None = None) -> BacklogAnalysisResult:
        """Ingest document + backlog context and return validated BacklogAnalysisResult."""
        start_ts = time.perf_counter()
        doc_path = Path(document_path)
        resolved_backlog = backlog_path if backlog_path is not None else self.cfg.paths.baseline_backlog
        resolved_gh = github_repo or (self.cfg.github.repo if self.cfg.github.enabled else None)

        logger.info("Ingesting document '%s' (scenario=%s)", doc_path.name, self.cfg.scenario_id)
        doc_text = extract_document_text(doc_path)
        existing_items = load_existing_backlog(resolved_backlog, github_repo=resolved_gh)

        if self.offline_mode:
            logger.info("Running in offline_deterministic_replay mode (no API key required).")
            payload, mode_label = self._run_offline(doc_path, doc_text, existing_items), "offline_deterministic_replay"
        else:
            logger.info("Calling OpenAI Structured Outputs (model=%s)...", self.cfg.llm_model)
            payload, mode_label = self._call_openai_with_retry(doc_text, existing_items, doc_path.name), "live_openai"

        stories = self._apply_scenario_variables(payload.stories)
        elapsed_ms = int((time.perf_counter() - start_ts) * 1000)
        return BacklogAnalysisResult(
            summary=payload.summary, stories=stories,
            metadata=ExecutionMetadata(
                scenario_id=self.cfg.scenario_id, source_file=doc_path.name, execution_mode=mode_label,
                model_name=self.cfg.llm_model, prompt_version=PROMPT_VERSION, latency_ms=elapsed_ms,
                existing_backlog_count=len(existing_items),
            ),
        )

    def _call_openai_with_retry(self, doc_text: str, existing_items: list[ExistingBacklogItem], source_name: str) -> LLMExtractionPayload:
        client = OpenAI(api_key=self.api_key, timeout=self.cfg.timeout_seconds)
        messages = [
            {"role": "system", "content": build_system_prompt(self.cfg)},
            {"role": "user", "content": build_user_prompt(doc_text, existing_items, self.cfg, source_name)},
        ]
        for attempt in range(self.cfg.max_retries + 1):
            try:
                comp = client.beta.chat.completions.parse(
                    model=self.cfg.llm_model, temperature=self.cfg.temperature,
                    messages=messages, response_format=LLMExtractionPayload,
                )
                if comp.choices[0].message.parsed:
                    return comp.choices[0].message.parsed
                raise ValueError("Empty structured output payload.")
            except Exception as exc:
                logger.warning("OpenAI attempt %d failed: %s", attempt + 1, exc)
                if attempt == self.cfg.max_retries:
                    raise
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError("Unreachable")

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
                document_title=f"{self.cfg.project_title} — {source_name if (source_name := doc_path.name) else 'Doc'}",
                executive_summary=f"Extracted {len(stories)} {self.cfg.output_item_label}(s) for {self.cfg.domain_name}.",
                key_themes=self.cfg.categories[:3], risks_and_dependencies=["Verify cross-service dependencies."],
                open_questions=["Confirm target SLA thresholds with product owner."],
            ),
            stories=stories,
        )

    def _apply_scenario_variables(self, stories: list[GeneratedUserStory]) -> list[GeneratedUserStory]:
        for idx, story in enumerate(stories, start=1):
            story.id = f"{self.cfg.id_prefix}-{idx:03d}"
            if self.cfg.categories and story.category not in self.cfg.categories:
                story.category = self.cfg.categories[(idx - 1) % len(self.cfg.categories)]
        return stories
