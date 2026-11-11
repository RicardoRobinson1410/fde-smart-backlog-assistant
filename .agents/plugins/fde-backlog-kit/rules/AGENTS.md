# FDE Project Engineering Rules (Parameterized Architecture)

1. **Zero Hardcoded Scenario Assumptions**: Never hardcode domain names, ID prefixes, categories, or priority rubrics inside `engine.py` or `prompts.py`. Always read from `ScenarioConfig` (`config/scenario_config.json` or `config/presets/*.json`).
2. **Strict Schema Validation**: Every LLM or offline output must pass `BacklogAnalysisResult` Pydantic v2 validation (`src/backlog_assistant/models.py`).
3. **200-500 LOC Core Scope**: Keep `src/backlog_assistant/*.py` concise, readable, and within the 200-500 LOC RDE Certification guideline.
4. **Offline Reviewer Guarantee**: All CLI commands, Streamlit workflows, and `pytest` suites must succeed without requiring an active `OPENAI_API_KEY`.
