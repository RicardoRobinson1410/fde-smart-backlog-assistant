# Architecture, Prompt Engineering Evolution & AI Usage Log

This document fulfills **Required Steps 1, 2, 3, and 5** of the Certified-Level RDE Candidate Job Aid, detailing our prompt design methodology, testing rubric, agent/subagent/MCP/hook schemas, and reflection on AI-assisted development.

---

## 1. Prompt Engineering Evolution (`v1` $\rightarrow$ `v3.0-fde-configurable`)

### Iteration 1 (`v1` — Naive Zero-Shot Prompt)
- **Prompt**: *"Read the following meeting notes and generate Agile user stories with acceptance criteria and priorities in JSON format."*
- **Observed Failure Modes**:
  1. **Unbounded Priority Inflation**: Marked almost every item as `"High"` or `"Critical"` without justification.
  2. **Untestable Acceptance Criteria**: Produced vague criteria such as *"System should be fast and secure"*.
  3. **Backlog Blindness**: Re-created stories that were already in `existing_backlog.json` (`FIN-101`).
  4. **Hallucinated Details**: Invented specific retention windows (e.g., `"90 days"`) when the input notes left them unspecified.

### Iteration 2 (`v2` — Persona + Explicit Prioritization & Sizing Rubric)
- **Improvements**: Introduced the Staff FDE persona, Fibonacci story point constraints (`[1, 2, 3, 5, 8, 13]`), and a 4-tier `P0–P3` rubric requiring a `priority_rationale` field.
- **Remaining Gap**: Still lacked structured cross-referencing against existing backlog IDs and hardcoded FinTech domain assumptions.

### Iteration 3 (`v3.0-fde-configurable` — Parameterized Context-Grounded Prompt in `src/backlog_assistant/prompts.py`)
- **Key Innovations**:
  1. **Externalized Scenario Variables (`ScenarioConfig`)**: Dynamically injects `agent_role`, `domain_name`, `output_item_label`, `id_prefix`, `story_template`, `categories`, and `priority_rubric` from JSON configuration.
  2. **4-State Backlog Alignment Classification**: Forces the model to compare every extracted requirement against the injected `existing_backlog.json` (or live GitHub Issues) and classify it as `NEW`, `UPDATES_EXISTING`, `DUPLICATE`, or `CONFLICT` with explicit `related_backlog_ids`.
  3. **Anti-Hallucination Escape Hatch (`summary.open_questions`)**: Explicitly instructs the model to route missing SLAs, retention windows, or architectural ambiguities into `open_questions` rather than guessing.
  4. **Pydantic v2 Structural Enforcement**: Paired with LangChain/OpenAI Structured Outputs (`ChatOpenAI.with_structured_output(LLMExtractionPayload)`) inside a 4-node LangGraph `StateGraph` (`ingest_node` $\rightarrow$ `extractor_agent` $\rightarrow$ `backlog_auditor` $\rightarrow$ `security_reviewer`) and a Pydantic `@field_validator` enforcing $\ge 3$ non-empty, testable acceptance criteria per item.

---

## 2. How AI Was Used in the Development Process

Per the Job Aid constraint (*"Show how AI was used in your development process"*):
1. **Problem & Rubric Refinement**: Used AI pair-programming to stress-test the 3 sample scenarios (`01_sprint_planning_notes.txt`, `02_incident_postmortem.md`, `03_pci_compliance_spec.pdf`) so that all four alignment states (`NEW`, `UPDATES_EXISTING`, `DUPLICATE`, `CONFLICT`) are deterministically exercised.
2. **Schema & Guardrail Co-Design**: Iterated on Pydantic v2 models (`src/backlog_assistant/models.py`) to guarantee strict type safety between OpenAI's `response_format` and downstream Markdown/GitHub Issue exporters.
3. **Subagent & Hook Automation (`.agents/`)**: Configured dedicated subagents (`backlog-auditor`, `security-reviewer`) and a `PreToolUse` safety hook (`scripts/hooks/pre_tool_gate.py`) to audit generated artifacts and guard command execution.

---

## 3. Reflection: What Worked Well & Future Improvements

### What Worked Well
- **Scenario Parameterization (`ScenarioConfig`)**: Decoupling domain variables into `config/scenario_config.json` and `config/presets/incident_triage_scenario.json` allowed the exact same ~690-LOC core engine (`config.py`, `models.py`, `parser.py`, `prompts.py`, `engine.py`, `cli.py`) to serve both Agile Product Backlog management and SRE Incident Postmortem triage, alongside the optional evaluation harness (`evaluation.py`) and 8-tab Streamlit FDE Portal (`app.py`).
- **Dual Execution Mode (Live OpenAI + Deterministic Offline Replay)**: Reviewers can run `pytest` and the CLI evaluator in under 2 seconds without needing an API key, while live API calls benefit from schema-enforced Structured Outputs and exponential backoff.

### What We Would Improve for Production Scale
1. **Vector / Hybrid Retrieval for Large Backlogs (RAG)**: Injecting the full JSON backlog works well up to ~100 items; for enterprise Jira/GitHub backlogs with 10,000+ tickets, we would add an embedding + BM25 hybrid retrieval pre-filter (top-15 candidate tickets per section) before calling the LLM.
2. **Async Batch Processing & Token Cost Telemetry**: Switch to `AsyncOpenAI` for multi-document ingestion and persist token/cost metrics to OpenTelemetry / Prometheus.
3. **Two-Way Jira / Linear / GitHub Webhook Sync**: Extend the existing `gh issue` integration into a bidirectional webhook listener with human-in-the-loop approval in Slack/Teams.

