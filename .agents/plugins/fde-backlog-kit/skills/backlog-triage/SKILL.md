---
name: backlog-triage
description: Step-by-step runbook for adapting ScenarioConfig variables, running backlog extraction, and verifying the Golden Evaluation Rubric.
---

# Skill: Configurable FDE Backlog Triage

1. **Select or Adapt Scenario Variables**:
   - Inspect `config/scenario_config.json` or pass `--config config/presets/<preset>.json`.
   - Override individual variables at runtime via `--set domain_name="..." --set id_prefix="REQ"`.
2. **Execute Document Analysis**:
   - Run `python -m backlog_assistant.cli analyze <input_path> --output-dir outputs`.
3. **Run Golden Rubric Verification**:
   - Run `python -m backlog_assistant.cli evaluate` and `pytest` to confirm 100% rubric compliance.

