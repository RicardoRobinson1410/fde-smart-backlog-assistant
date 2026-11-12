# AI Agent, Subagents, MCP, Hooks & Tools Architecture

> [!IMPORTANT]
> **Evaluation & Code Review Note**:
> Reviewers evaluating the **AI Agent, Prompt Engineering, Subagents, MCP, Hooks, and Tools implementation** only need to inspect this **`agent/`** folder!
> 
> The code in `src/backlog_assistant/` contains the runnable Python package (including the Streamlit web portal `app.py`, terminal CLI `cli.py`, and test harness `evaluation.py`). **Do NOT delete `src/backlog_assistant/`**, as `app.py`, `pytest`, and the interactive UI rely on it to execute. The `agent/` folder is the condensed, clean extraction dedicated strictly to checking the agentic components without the UI noise.

## Structure

```
agent/
├── README.md                    # This architecture and evaluation guide
├── plugin.json                  # Antigravity / IDE plugin manifest
├── agents/                      # Main Agent Orchestration & Prompts
│   ├── engine.py                # Lean (~90 lines) LangGraph StateGraph (Ingest -> Extractor -> Auditor -> Security Reviewer)
│   ├── prompts.py               # Parameterized v3.0 prompt templates, CoT extraction & anti-hallucination guardrails
│   ├── config.py                # ScenarioConfig loader (hot-swappable domain variables & rubric)
│   └── scenario_config.json     # Default FinTech backlog configuration
├── functions/                   # Modular Agent Node & Pipeline Functions
│   ├── __init__.py              # Re-exports clean function interfaces
│   ├── nodes.py                 # LangGraph individual node functions (ingest, extractor, auditor, security) + offline replay
│   ├── llm_caller.py            # LangChain LCEL structured output invoker (ChatOpenAI.with_structured_output)
│   └── finops.py                # Token cost estimation & immutable JSONL audit trail logging
├── subagents/                   # Specialized Subagent Manifests
│   ├── backlog-auditor.md       # Subagent that compares extracted items against baseline IDs (NEW/UPDATE/DUP/CONFLICT)
│   └── security-reviewer.md     # Subagent that audits P0 blast radius, encryption & PCI compliance for HITL approval
├── tools/                       # Local Python Tools & Schemas
│   ├── parser.py                # Document text extraction (.txt/.md/.pdf via pypdf) + zero-trust PII/secret scrubbing
│   └── models.py                # Pydantic v2 schemas enforcing >=3 testable acceptance criteria & Fibonacci sizing
├── mcp/                         # Model Context Protocol (MCP) Server Configuration
│   └── mcp_config.json          # fde-backlog-stdio MCP integration (loads and syncs backlog over standard I/O)
├── hooks/                       # Lifecycle Safety Hooks
│   ├── hooks.json               # PreToolUse event hook configuration
│   └── pre_tool_gate.py         # Interceptor verifying command safety & path boundaries before execution
└── skills/                      # Skills & Behavioral Rules
    ├── AGENTS.md                # FDE operating guidelines & constraints
    └── backlog-triage/
        └── SKILL.md             # Standard operating procedure for ingesting and triaging requirements
```

## How the Agent Pipeline Executes

1. **Safety Interception (`hooks/`)**: `hooks.json` triggers `pre_tool_gate.py` to inspect tool arguments before any action is executed.
2. **Ingestion & Privacy Tool (`tools/parser.py`)**: Reads the requirement document (`.txt`, `.md`, or `.pdf`), hashes it with SHA-256, and masks emails, PANs, SSNs, and API keys locally using regex before any LLM call.
3. **Multi-Agent Orchestration (`agents/engine.py` + `agents/prompts.py`)**:
   - **`ingest_node`**: Loads scrubbed text and queries baseline tickets via the `fde-backlog-stdio` MCP server (`mcp/mcp_config.json`).
   - **`extractor_agent` (`gpt-4o-mini`)**: Uses dynamic prompt templates (`agents/prompts.py`) with `ChatOpenAI.with_structured_output` to synthesize user stories and route unstated specs to `open_questions`.
   - **`backlog_auditor` subagent (`subagents/backlog-auditor.md`)**: Compares stories against existing tickets to classify `NEW`, `UPDATES_EXISTING`, `DUPLICATE`, or `CONFLICT`.
   - **`security_reviewer` subagent (`subagents/security-reviewer.md` via `gpt-4o`)**: Conducts frontier-model compliance & blast-radius checks, flagging critical items for Human-in-the-Loop (HITL) approval.
4. **Schema Guardrails (`tools/models.py`)**: Pydantic v2 validates output structure, guaranteeing that every accepted story contains at least 3 testable acceptance criteria.

