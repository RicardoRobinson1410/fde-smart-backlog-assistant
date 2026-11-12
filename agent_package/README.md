# Smart Backlog Assistant — Consolidated Agent Review Folder

This folder groups **all files related to the AI agent** in one place so reviewers can inspect the implementation, prompts, subagents, MCP/hooks, evaluation dataset, samples, and documentation without hunting across the repository.

> **Note:** The runnable source of truth remains at the repository root (`src/`, `config/`, `.agents/`, `evals/`, `data/`, `docs/`) so `pytest`, `backlog_assistant.cli`, and `streamlit run src/backlog_assistant/app.py` continue to work without breaking imports.

## Folder Map

| Subfolder | Contents |
| :--- | :--- |
| `code/backlog_assistant/` | Core LangGraph + OpenAI agent (`engine.py`, `prompts.py`, `models.py`, `parser.py`, `config.py`, `cli.py`, `evaluation.py`, `app.py`) |
| `config/` | Scenario configuration (`scenario_config.json`) & presets (`presets/incident_triage_scenario.json`) |
| `agent_kit/` | Subagents (`backlog-auditor.md`, `security-reviewer.md`), `mcp_config.json`, `hooks.json`, `plugin.json`, `rules/AGENTS.md`, `skills/backlog-triage/SKILL.md`, and `hooks/pre_tool_gate.py` |
| `evals/` | 12-case golden evaluation dataset (`golden_dataset.json`) & frozen backlog fixture (`fixtures/eval_backlog.json`) |
| `samples/` | 3 realistic sample inputs (`inputs/`), expected outputs (`expected_outputs/`), and baseline backlog (`existing_backlog.json`) |
| `docs/` | `RDE_Step1_Step2_Problem_and_Design.pdf`, `ARCHITECTURE_AND_PROMPTS.md`, and `INTERVIEW_PREP_GUIDE.md` |
