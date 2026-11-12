# Part 4: RDE Council Interview Defense & Q&A Guide

Use this guide during your 1-hour interview with the Accenture RDE Global Council reviewer.

---

## 1. 60-Second Elevator Pitch
> *"For my Hands-On Project, I built a **Configurable FDE Smart Backlog Assistant**. In real client engagements, FDEs constantly switch domains—from FinTech sprint planning to SRE incident postmortems or PCI compliance audits. Instead of hardcoding prompts for one narrow sample, I designed a **scenario-driven architecture** (`ScenarioConfig`) within a clean ~440-LOC Python package. It ingests `.txt`, `.md`, and `.pdf` specs, cross-references them against an existing JSON backlog or live GitHub Issues, and uses OpenAI Structured Outputs with Pydantic v2 guardrails to produce deduplicated user stories (`NEW`, `UPDATES_EXISTING`, `DUPLICATE`, `CONFLICT`) while routing missing specs into `open_questions` to prevent hallucination."*

---

## 2. Live Demo Script (3 Minutes)
1. **Show the Golden Evaluation Scorecard (30s)**:
   ```powershell
   python -m backlog_assistant.cli evaluate
   ```
   *Highlight*: Point out how all 3 realistic scenarios pass `>= 3 Acceptance Criteria`, catch the duplicate (`FIN-101`), update existing scope (`FIN-104`, `FIN-105`), and flag the PCI encryption conflict (`FIN-106`).
2. **Demonstrate Live Variable Adaptation (60s)**:
   ```powershell
   python -m backlog_assistant.cli analyze data/samples/02_incident_postmortem.md `
     --config config/presets/incident_triage_scenario.json `
     --set id_prefix=SRE
   ```
   *Highlight*: Show that without changing any code, the persona, rubric, categories, and ticket IDs (`SRE-001`) adapt to Site Reliability Engineering.
3. **Show the Interactive 8-Tab FDE Streamlit Portal (60s)**:
   ```powershell
   python -m streamlit run src/backlog_assistant/app.py
   ```
   *Highlight*: Show the **Active Project** badge in the top-left, switch projects in **Tab 8 (Project & Settings)** to demonstrate per-project data isolation (Kanban, FinOps, Evals, Audit Logs), run a case in **Tab 5 (Agent Evaluation Lab)** with the calibrated AI Judge, and inspect the 5-stage pipeline in **Tab 7 (Agent & MCP Graph)**.

---

## 3. High-Probability Council Questions & Model Answers

### Q1: "Why did you use OpenAI Structured Outputs + Pydantic v2 instead of just asking for JSON in the prompt?"
- **Answer**: Prompt-only JSON instructions fail in production when documents contain unescaped quotes or when the model omits required fields. Using `client.beta.chat.completions.parse` with a Pydantic v2 schema enforces grammar-constrained decoding at the token level, and our custom `@field_validator` guarantees business invariants (such as $\ge 3$ non-empty testable acceptance criteria).

### Q2: "How does your solution prevent hallucinations when input notes are incomplete?"
- **Answer**: LLMs naturally try to 'fill in the blanks' (e.g., inventing a 7-year retention period or a 100ms latency SLA when none was stated). In `prompts.py` (`v3.0-fde-configurable`), we explicitly provide a dedicated schema sink (`summary.open_questions`) and instruct the model never to invent unstated non-functional requirements.

### Q3: "What happens if the existing backlog has 15,000 Jira/GitHub tickets instead of 10?"
- **Answer**: Passing 15,000 tickets directly in the context window would exceed token budgets and degrade attention ("lost in the middle" phenomenon). At enterprise scale, we keep the exact same `BacklogEngine` interface but insert a **RAG pre-retrieval stage** (using `pgvector` or Azure AI Search with hybrid dense + BM25 keyword search) to retrieve the top-10 semantically similar backlog items per document section before invoking the structured extraction prompt.

### Q4: "How do Agents, Subagents, MCP servers, and Lifecycle Hooks fit into this architecture?"
- **Answer**:
  - **Main Agent**: Orchestrates the end-to-end workflow and user interaction.
  - **Subagents (`.agents/plugins/fde-backlog-kit/agents/`)**: Isolate context-heavy review tasks—`backlog-auditor` verifies rubric & deduplication accuracy, while `security-reviewer` checks PCI-DSS/compliance coverage.
  - **MCP Servers (`mcp_config.json`)**: Standardize tool access over `stdio` or `Streamable HTTP` (`/mcp`) so the agent can query local backlogs or remote GitHub Issues through a unified protocol.
  - **Lifecycle Hooks (`hooks.json`)**: Enforce deterministic guardrails outside the LLM—such as our `PreToolUse` gate (`scripts/hooks/pre_tool_gate.py`) that blocks destructive shell commands before execution.

