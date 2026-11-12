"""Centralized FDE Command & Metrics Portal (Streamlit + Plotly) — Didactic Workbench, FinOps, Governance & Rubric Tracker."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from backlog_assistant.config import ScenarioConfig, load_scenario_config
from backlog_assistant.engine import BacklogEngine
from backlog_assistant.models import BacklogAlignment, BacklogAnalysisResult
from backlog_assistant.parser import (
    export_stories_to_github,
    extract_document_text,
    load_existing_backlog,
    redact_pii_and_secrets,
)

st.set_page_config(page_title="FDE Centralized Engineering Portal", page_icon="⚡", layout="wide")


def load_audit_history(audit_path: str | Path) -> list[dict[str, Any]]:
    """Load append-only compliance audit records from outputs/audit_trail.jsonl."""
    path = Path(audit_path)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    return list(reversed(records))


def ensure_initial_telemetry(cfg: ScenarioConfig) -> list[dict[str, Any]]:
    """Seed baseline telemetry across the 3 golden scenarios on first portal launch so charts are immediately populated."""
    history = load_audit_history(cfg.paths.audit_log_path)
    if not history:
        seed_engine = BacklogEngine(config=cfg, force_offline=True)
        samples_dir = Path(cfg.paths.samples_dir)
        for sample_file in sorted(p for p in samples_dir.iterdir() if p.suffix.lower() in {".txt", ".md", ".pdf"}):
            res = seed_engine.analyze(sample_file)
            if "latest_result" not in st.session_state:
                st.session_state["latest_result"] = res
        history = load_audit_history(cfg.paths.audit_log_path)
    elif "latest_result" not in st.session_state:
        st.session_state["latest_result"] = BacklogEngine(config=cfg, force_offline=True).analyze(
            Path(cfg.paths.samples_dir) / "01_sprint_planning_notes.txt"
        )
    return history


def render_sidebar() -> tuple[ScenarioConfig, bool, bool]:
    """Render didactic sidebar controls for hot-swapping scenario variables and subagent models."""
    st.sidebar.title("⚙️ FDE Control Plane")
    st.sidebar.caption("Modify variables below to adapt the entire pipeline to any client domain in real time.")

    presets = {
        "Default: FinTech Smart Backlog": "config/scenario_config.json",
        "Preset 2: SRE Incident Triage": "config/presets/incident_triage_scenario.json",
    }
    preset_choice = st.sidebar.selectbox("1. Scenario Preset", list(presets.keys()))
    base_cfg = load_scenario_config(presets[preset_choice])

    with st.sidebar.expander("2. Domain & Persona Variables", expanded=True):
        domain_name = st.text_input("Domain (`domain_name`)", value=base_cfg.domain_name)
        agent_role = st.text_input("Persona (`agent_role`)", value=base_cfg.agent_role)
        item_label = st.text_input("Work Item Label (`output_item_label`)", value=base_cfg.output_item_label)
        id_prefix = st.text_input("Ticket ID Prefix (`id_prefix`)", value=base_cfg.id_prefix)

    with st.sidebar.expander("3. Subagent Model Routing (FinOps)", expanded=True):
        st.caption("Route high-volume tasks to mini models and reserve flagship models for security audits.")
        m_ext = st.text_input("Extractor Agent Model", value=base_cfg.subagent_models.extractor_agent)
        m_aud = st.text_input("Backlog Auditor Model", value=base_cfg.subagent_models.backlog_auditor)
        m_sec = st.text_input("Security Reviewer Model", value=base_cfg.subagent_models.security_reviewer)

    with st.sidebar.expander("4. Privacy, GitHub & Execution Mode", expanded=True):
        pii_guard = st.checkbox("Enable Pre-LLM PII Redaction", value=base_cfg.enable_pii_redaction)
        use_live_gh = st.checkbox("Sync Live GitHub Issues Backlog", value=False)
        gh_repo = st.text_input("GitHub Repo (`owner/repo`)", value=base_cfg.github.repo)
        offline = st.checkbox("Force Offline Deterministic Mode", value=False)

    cfg = base_cfg.with_overrides({
        "domain_name": domain_name,
        "agent_role": agent_role,
        "output_item_label": item_label,
        "id_prefix": id_prefix,
        "enable_pii_redaction": pii_guard,
        "github.repo": gh_repo,
        "subagent_models.extractor_agent": m_ext,
        "subagent_models.backlog_auditor": m_aud,
        "subagent_models.security_reviewer": m_sec,
    })
    return cfg, offline, use_live_gh


def render_top_kpi_banner(history: list[dict[str, Any]], latest: BacklogAnalysisResult | None) -> None:
    """Render the 6 centralized FDE KPI metric cards across the top of the portal."""
    total_runs = len(history)
    total_pii = sum(int(r.get("pii_redacted_count", 0)) for r in history)
    total_tokens = sum(int(r.get("estimated_tokens", 0)) for r in history)
    total_cost = sum(float(r.get("estimated_cost_usd", 0.0)) for r in history)
    total_hitl = sum(int(r.get("hitl_approval_required_count", 0)) for r in history)

    if latest:
        dedup_caught = sum(
            1 for s in latest.stories if s.backlog_alignment in {BacklogAlignment.DUPLICATE, BacklogAlignment.CONFLICT}
        )
        ac_pass_pct = int(
            100 * sum(1 for s in latest.stories if len(s.acceptance_criteria) >= 3) / max(1, len(latest.stories))
        )
    else:
        dedup_caught = 0
        ac_pass_pct = 100

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Audited Runs", str(total_runs), f"{len({r.get('document_sha256') for r in history})} unique SHA-256")
    c2.metric("PII / Secrets Masked", str(total_pii), "Zero-Trust Pre-LLM Shield")
    c3.metric("Cumulative Tokens", f"{total_tokens:,}", "Input + Output Budget")
    c4.metric("FinOps Spend (USD)", f"${total_cost:.5f}", "-94% via Tiered Routing")
    c5.metric("HITL Gates Triggered", str(total_hitl), "P0 / Conflict Governance")
    c6.metric("Rubric Compliance", f"{ac_pass_pct}%", f"{dedup_caught} overlap/conflict in run")


def render_portal() -> None:
    cfg, offline, use_live_gh = render_sidebar()
    history = ensure_initial_telemetry(cfg)
    latest_res: BacklogAnalysisResult | None = st.session_state.get("latest_result")

    st.title(f"⚡ {cfg.project_title} — Centralized FDE Portal")
    st.markdown(
        f"**Active Scenario**: `{cfg.scenario_id}` | **Domain**: `{cfg.domain_name}` | "
        f"**Persona**: *{cfg.agent_role}* | **Tiered Models**: `{cfg.subagent_models.extractor_agent}` $\\rightarrow$ `{cfg.subagent_models.security_reviewer}`"
    )

    render_top_kpi_banner(history, latest_res)
    st.divider()

    tab_work, tab_metrics, tab_graph, tab_eval, tab_guide = st.tabs([
        "🚀 1. Interactive Workbench",
        "📊 2. FDE Metrics, FinOps & Charts",
        "🧠 3. LangGraph Multi-Agent Router",
        "🏆 4. Golden Rubric Evaluator",
        "🎓 5. Didactic FDE Guide & Config",
    ])

    # ---------------- TAB 1: INTERACTIVE WORKBENCH ----------------
    with tab_work:
        st.info(
            "**Didactic Workflow (4 Steps):** "
            "① Select a sample document or upload your own (`.txt`, `.md`, `.pdf`) $\\rightarrow$ "
            "② Inspect the Pre-LLM PII Shield & Baseline Backlog $\\rightarrow$ "
            "③ Execute the 4-Node LangGraph Pipeline $\\rightarrow$ "
            "④ Review extracted items, approve HITL gates, and export to GitHub Issues."
        )
        col_in, col_bl = st.columns([3, 2])
        with col_in:
            st.subheader("Step 1: Select or Upload Requirement Document")
            samples_dir = Path(cfg.paths.samples_dir)
            samples = sorted(p.name for p in samples_dir.glob("*") if p.suffix.lower() in {".txt", ".md", ".pdf"})
            selected_sample = st.selectbox("Choose a sample engineering scenario:", samples)
            uploaded = st.file_uploader("Or upload a custom file (.txt, .md, .pdf):", type=["txt", "md", "pdf"])

            if uploaded is not None:
                with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded.name).suffix) as tmp:
                    tmp.write(uploaded.getvalue())
                    active_doc_path = Path(tmp.name)
            else:
                active_doc_path = samples_dir / selected_sample

            raw_preview = extract_document_text(active_doc_path)
            scrubbed_preview, preview_pii_count = (
                redact_pii_and_secrets(raw_preview) if cfg.enable_pii_redaction else (raw_preview, 0)
            )
            with st.expander(
                f"🔍 Step 1b: Inspect Document Text & Pre-LLM PII Shield ({preview_pii_count} PII tokens detected)",
                expanded=False,
            ):
                p1, p2 = st.columns(2)
                p1.text_area("Raw Document Text", raw_preview, height=150, disabled=True)
                p2.text_area("Sanitized Text Sent to LLM", scrubbed_preview, height=150, disabled=True)

        with col_bl:
            st.subheader("Step 2: Baseline Backlog Context")
            gh_target = cfg.github.repo if use_live_gh else None
            existing_items = load_existing_backlog(
                None if use_live_gh else cfg.paths.baseline_backlog, github_repo=gh_target
            )
            st.caption(
                f"Loaded **{len(existing_items)}** baseline items from "
                f"`{'GitHub: ' + gh_target if use_live_gh else cfg.paths.baseline_backlog}`"
            )
            st.dataframe([i.model_dump() for i in existing_items], use_container_width=True, height=210)

        if st.button(
            f"▶ Step 3: Execute LangGraph Pipeline & Generate {cfg.output_item_label}s",
            type="primary",
            use_container_width=True,
        ):
            engine = BacklogEngine(config=cfg, force_offline=offline)
            latest_res = engine.analyze(
                active_doc_path,
                backlog_path="" if use_live_gh else cfg.paths.baseline_backlog,
                github_repo=gh_target,
            )
            st.session_state["latest_result"] = latest_res
            st.rerun()

        if latest_res:
            m = latest_res.metadata
            st.success(
                f"✅ **Run Complete** | Mode: `{m.execution_mode}` | Latency: `{m.latency_ms} ms` | "
                f"SHA-256: `{m.document_sha256}` | PII Masked: `{m.pii_redacted_count}` | "
                f"Tokens: `{m.estimated_tokens}` | Est. Cost: `${m.estimated_cost_usd:.6f}`"
            )
            s_col1, s_col2 = st.columns(2)
            with s_col1:
                st.markdown(f"#### 📋 Executive Summary: `{latest_res.summary.document_title}`")
                st.write(latest_res.summary.executive_summary)
                st.markdown("**Key Themes:** " + " • ".join(f"`{t}`" for t in latest_res.summary.key_themes))
            with s_col2:
                st.warning(
                    "**Risks & Dependencies**\n" + "\n".join(f"- {r}" for r in latest_res.summary.risks_and_dependencies)
                )
                st.info(
                    "**Open Questions for Stakeholders (Anti-Hallucination Guardrail)**\n"
                    + "\n".join(f"- [ ] {q}" for q in latest_res.summary.open_questions)
                )

            st.markdown(f"#### 🎯 Step 4: Review Extracted {cfg.output_item_label}s ({len(latest_res.stories)} items)")
            filter_align = st.multiselect(
                "Filter by Backlog Alignment:",
                options=[a.value for a in BacklogAlignment],
                default=[a.value for a in BacklogAlignment],
            )
            for s in latest_res.stories:
                if s.backlog_alignment.value not in filter_align:
                    continue
                hitl_tag = " ⚠️ [HITL APPROVAL REQUIRED]" if s.requires_human_approval else " ✅ [Auto-Verified]"
                refs = f" (Refs: {', '.join(s.related_backlog_ids)})" if s.related_backlog_ids else ""
                with st.expander(
                    f"{s.id} | [{s.backlog_alignment.value}{refs}] {s.title} — {s.priority} ({s.story_points} pts){hitl_tag}",
                    expanded=True,
                ):
                    k1, k2, k3, k4 = st.columns(4)
                    k1.markdown(f"**Priority:** `{s.priority}`")
                    k2.markdown(f"**Category:** `{s.category}`")
                    k3.markdown(f"**Confidence:** `{int(s.confidence_score * 100)}%`")
                    k4.markdown(f"**Story Points:** `{s.story_points} pts`")
                    st.markdown(f"**{cfg.output_item_label}:** *{s.user_story}*")
                    st.markdown(f"**Technical Description:** {s.technical_description}")
                    st.caption(
                        f"**Priority Rationale:** {s.priority_rationale} | **Alignment Notes:** {s.alignment_notes}"
                    )
                    st.markdown(
                        "**Testable Acceptance Criteria:**\n"
                        + "\n".join(f"- [x] {ac}" for ac in s.acceptance_criteria)
                    )

            b1, b2, b3 = st.columns(3)
            b1.download_button(
                "⬇ Download JSON Payload",
                latest_res.model_dump_json(indent=2),
                file_name="fde_result.json",
                use_container_width=True,
            )
            b2.download_button(
                "⬇ Download Markdown Report",
                latest_res.to_markdown(cfg),
                file_name="fde_report.md",
                use_container_width=True,
            )
            if b3.button("🐙 Preview / Export NEW Stories to GitHub Issues", use_container_width=True):
                exported = export_stories_to_github(
                    latest_res.stories, repo=cfg.github.repo, labels=cfg.github.issue_labels, dry_run=True
                )
                for line in exported:
                    st.code(line)

    # ---------------- TAB 2: FDE METRICS, FINOPS & INTERACTIVE CHARTS ----------------
    with tab_metrics:
        st.subheader("📊 Centralized FDE Telemetry, FinOps & Governance Analytics")
        st.caption(
            "Interactive visualizations powered by `outputs/audit_trail.jsonl` and the active run's structured payload."
        )

        ch1, ch2, ch3 = st.columns(3)
        with ch1:
            if latest_res:
                align_counts: dict[str, int] = {}
                for s in latest_res.stories:
                    align_counts[s.backlog_alignment.value] = align_counts.get(s.backlog_alignment.value, 0) + 1
                fig_align = px.pie(
                    names=list(align_counts.keys()),
                    values=list(align_counts.values()),
                    hole=0.55,
                    title="Backlog Alignment Breakdown (Latest Run)",
                )
                fig_align.update_layout(height=280, margin=dict(l=10, r=10, t=40, b=10))
                st.plotly_chart(fig_align, use_container_width=True)

        with ch2:
            tokens_used = latest_res.metadata.estimated_tokens if latest_res else 1200
            tiered_usd = round(tokens_used * 0.30 / 1_000_000, 6)
            flagship_usd = round(tokens_used * 5.00 / 1_000_000, 6)
            fig_cost = go.Figure(
                data=[
                    go.Bar(
                        x=["Tiered Subagents (4o-mini -> 4o)", "All-Flagship (gpt-4o only)"],
                        y=[tiered_usd, flagship_usd],
                        text=[f"${tiered_usd:.5f}", f"${flagship_usd:.5f}"],
                        textposition="auto",
                    )
                ]
            )
            fig_cost.update_layout(
                title="FinOps Cost per Run (USD): Tiered vs. Flagship",
                yaxis_title="USD ($)",
                height=280,
                margin=dict(l=10, r=10, t=40, b=10),
            )
            st.plotly_chart(fig_cost, use_container_width=True)

        with ch3:
            if history:
                run_labels = [f"Run #{len(history) - idx} ({r.get('source_file', '')[:12]})" for idx, r in enumerate(history[:8])]
                tokens_series = [int(r.get("estimated_tokens", 0)) for r in history[:8]]
                hitl_series = [int(r.get("hitl_approval_required_count", 0)) * 200 for r in history[:8]]
                fig_hist = go.Figure()
                fig_hist.add_trace(go.Bar(x=run_labels, y=tokens_series, name="Est. Tokens"))
                fig_hist.add_trace(go.Scatter(x=run_labels, y=hitl_series, name="HITL Trigger (Scaled)", mode="lines+markers"))
                fig_hist.update_layout(
                    title="Token Budget & HITL Triggers Across Runs",
                    height=280,
                    margin=dict(l=10, r=10, t=40, b=10),
                )
                st.plotly_chart(fig_hist, use_container_width=True)

        st.markdown("#### 📜 Append-Only Compliance Audit Log (`outputs/audit_trail.jsonl`)")
        st.dataframe(history, use_container_width=True, height=250)

    # ---------------- TAB 3: LANGGRAPH MULTI-AGENT ROUTER ----------------
    with tab_graph:
        st.subheader("🧠 Compiled LangGraph `StateGraph` Multi-Agent Pipeline")
        st.caption("Each node below is a dedicated agent stage with isolated responsibilities and cost-optimized model assignment.")

        n1, n2, n3, n4 = st.columns(4)
        with n1:
            st.markdown(
                "### 1️⃣ `ingest_node`\n"
                "**Role**: Ingestion & Privacy Shield\n\n"
                "- **Model**: *Deterministic Python*\n"
                "- **Actions**:\n"
                "  - Extracts `.txt`, `.md`, `.pdf`\n"
                "  - Computes `SHA-256` fingerprint\n"
                "  - Scrubs PII & API secrets\n"
                "  - Loads JSON / GitHub PAT backlog"
            )
        with n2:
            st.markdown(
                "### 2️⃣ `extractor_agent`\n"
                "**Role**: Structured Story Extractor\n\n"
                f"- **Model**: `{cfg.subagent_models.extractor_agent}`\n"
                "- **Actions**:\n"
                "  - Runs LangChain `with_structured_output`\n"
                "  - Enforces $\\ge 3$ testable ACs\n"
                "  - Classifies `NEW` / `DUPLICATE` / `CONFLICT`"
            )
        with n3:
            st.markdown(
                "### 3️⃣ `backlog_auditor`\n"
                "**Role**: Rubric & Dedup Auditor\n\n"
                f"- **Model**: `{cfg.subagent_models.backlog_auditor}`\n"
                "- **Actions**:\n"
                f"  - Applies `{cfg.id_prefix}-` prefix\n"
                "  - Validates category alignment\n"
                "  - Enforces `FIN-101` duplicate guardrail"
            )
        with n4:
            st.markdown(
                "### 4️⃣ `security_reviewer`\n"
                "**Role**: Compliance & HITL Gate\n\n"
                f"- **Model**: `{cfg.subagent_models.security_reviewer}`\n"
                "- **Actions**:\n"
                "  - Audits `P0` & `CONFLICT` stories\n"
                "  - Sets `requires_human_approval=True`\n"
                "  - Verifies `open_questions` sink"
            )

        st.divider()
        engine_preview = BacklogEngine(config=cfg, force_offline=True)
        g_col1, g_col2 = st.columns(2)
        with g_col1:
            st.markdown("##### Latest Run Execution Trace & Subagent Models Used")
            if latest_res:
                st.success(" $\\rightarrow$ ".join(f"`{node}`" for node in latest_res.metadata.agent_trace))
                st.json(latest_res.metadata.subagent_models_used)
        with g_col2:
            st.markdown("##### Compiled LangGraph Mermaid Definition (`workflow.get_graph().draw_mermaid()`)")
            st.code(engine_preview.get_graph_mermaid(), language="mermaid")

    # ---------------- TAB 4: GOLDEN RUBRIC EVALUATOR ----------------
    with tab_eval:
        st.subheader("🏆 Certified-Level RDE Golden Scenario Benchmark")
        st.caption(
            "Verify all 3 sample scenarios against the RDE Evaluation Rubric "
            "(>=3 testable ACs, deduplication accuracy, conflict detection, and open_questions)."
        )
        if st.button("▶ Run Full 3-Scenario Golden Evaluation Suite", type="primary"):
            eval_engine = BacklogEngine(config=cfg, force_offline=offline)
            samples_dir = Path(cfg.paths.samples_dir)
            rows = []
            for s_file in sorted(p for p in samples_dir.iterdir() if p.suffix.lower() in {".txt", ".md", ".pdf"}):
                r = eval_engine.analyze(s_file)
                ac_ok = all(len(st_item.acceptance_criteria) >= cfg.min_acceptance_criteria for st_item in r.stories)
                oq_ok = len(r.summary.open_questions) >= 1
                rows.append({
                    "Scenario File": s_file.name,
                    "SHA-256": r.metadata.document_sha256,
                    "Stories": len(r.stories),
                    "Min ACs >= 3": "✅ PASS" if ac_ok else "❌ FAIL",
                    "Alignments Detected": ", ".join(sorted({st_item.backlog_alignment.value for st_item in r.stories})),
                    "HITL Flagged": sum(1 for st_item in r.stories if st_item.requires_human_approval),
                    "Open Questions": len(r.summary.open_questions),
                    "Est. Tokens": r.metadata.estimated_tokens,
                    "Rubric Status": "✅ PASS" if (r.stories and ac_ok and oq_ok) else "❌ FAIL",
                })
            st.table(rows)

    # ---------------- TAB 5: DIDACTIC FDE GUIDE & CONFIG ----------------
    with tab_guide:
        st.subheader("🎓 10 Core Forward Deployed Engineer (FDE) Principles Implemented")
        st.markdown(
            "1. **Scenario-Driven Parameterization (`ScenarioConfig`)**: Swap domains, personas, ticket prefixes, and rubrics via JSON/env/UI without touching code.\n"
            "2. **Grammar-Constrained Structured Outputs**: Uses LangChain `with_structured_output(LLMExtractionPayload)` + Pydantic v2 validators (`>= 3` testable ACs).\n"
            "3. **4-State Backlog Grounding**: Every story is cross-referenced against existing items as `NEW`, `UPDATES_EXISTING`, `DUPLICATE`, or `CONFLICT`.\n"
            "4. **Anti-Hallucination Escape Hatch**: Missing SLAs or retention windows are routed to `summary.open_questions` instead of invented.\n"
            "5. **LangGraph Multi-Agent Orchestration**: Explicit `StateGraph` separating Ingestion, Extraction, Backlog Auditing, and Security Review.\n"
            "6. **FinOps Tiered Subagent Model Routing**: Routes extraction/audit to `gpt-4o-mini` and reserves `gpt-4o` for security review, tracking token & USD cost.\n"
            "7. **Pre-LLM Zero-Trust PII Shield**: Regex scrubber masks emails, API secrets, PANs, and SSNs before any external API call.\n"
            "8. **Human-in-the-Loop (HITL) Governance Gate**: Automatically flags `P0 - Critical`, `CONFLICT`, or `<80%` confidence items with `requires_human_approval=True`.\n"
            "9. **Idempotency & SHA-256 Input Fingerprinting**: Hashes every input document and prevents duplicate GitHub Issue creation.\n"
            "10. **Append-Only Compliance Audit Log**: Writes immutable telemetry records to `outputs/audit_trail.jsonl`."
        )
        st.markdown("##### Active `ScenarioConfig` JSON State")
        st.json(cfg.model_dump())


if __name__ == "__main__":
    render_portal()
