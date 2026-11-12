"""Parameterized prompt engineering templates dynamically constructed from ScenarioConfig."""

from __future__ import annotations

import json

from backlog_assistant.config import ScenarioConfig
from backlog_assistant.models import ExistingBacklogItem

PROMPT_VERSION = "v3.0-fde-configurable"


def build_system_prompt(cfg: ScenarioConfig) -> str:
    """Compile the system prompt dynamically from the active ScenarioConfig variables.

    Key Prompt Engineering Decisions (v1 -> v3 evolution):
    - v1 (Zero-shot): Produced vague acceptance criteria and ignored existing backlog duplicates.
    - v2 (Role + Rubric): Added explicit P0-P3 definitions and Fibonacci estimation rules.
    - v3 (Parameterized FDE Guardrails): Injects domain persona, customizable templates,
      existing backlog deduplication rules, and an anti-hallucination open_questions sink.
    """
    rubric_lines = "\n".join(f"  - {level}: {desc}" for level, desc in cfg.priority_rubric.items())
    constraints_lines = "\n".join(f"  {idx + 1}. {rule}" for idx, rule in enumerate(cfg.custom_constraints))

    return f"""You are an expert {cfg.agent_role} specializing in {cfg.domain_name}.
Mission: {cfg.domain_description}

### 1. Output Structure & Formatting Rules
- Generate structured `{cfg.output_item_label}` items with sequential IDs prefixed by `{cfg.id_prefix}-` (e.g., `{cfg.id_prefix}-001`).
- Format every `user_story` field strictly as: "{cfg.story_template}".
- Assign each item to one of these allowed categories: {cfg.categories}.
- Estimate effort using only this Fibonacci scale: {cfg.estimation_scale}.
- Include at least {cfg.min_acceptance_criteria} concrete, testable Acceptance Criteria per item.

### 2. Prioritization Rubric
Assign one of {cfg.priority_levels} and justify it in `priority_rationale` using this rubric:
{rubric_lines}

### 3. Existing Backlog De-Duplication & Alignment
Compare every candidate requirement against the provided Existing Backlog JSON:
- `NEW`: Net-new capability or requirement not covered in the existing backlog.
- `UPDATES_EXISTING`: Modifies scope, acceptance criteria, or priority of an existing item (cite IDs in `related_backlog_ids`).
- `DUPLICATE`: Already covered by an existing backlog item (cite IDs in `related_backlog_ids` so engineers do not duplicate work).
- `CONFLICT`: Contradicts an existing backlog item's architecture or constraints (cite IDs and explain in `alignment_notes`).

### 4. Scenario Guardrails & Anti-Hallucination
{constraints_lines}
"""


def build_user_prompt(
    document_text: str,
    existing_backlog: list[ExistingBacklogItem],
    cfg: ScenarioConfig,
    source_name: str = "input_document",
) -> str:
    """Construct the user prompt combining baseline backlog context and raw document text."""
    backlog_dump = json.dumps([item.model_dump() for item in existing_backlog], indent=2)
    return f"""### Scenario Context
- Scenario ID: `{cfg.scenario_id}`
- Domain: `{cfg.domain_name}`
- Source Document: `{source_name}`

### Existing Backlog Items ({len(existing_backlog)} items)
```json
{backlog_dump}
```

### Raw Input Document to Analyze
```text
{document_text}
```

Analyze the input document against the Existing Backlog and return the structured JSON payload matching the schema."""

