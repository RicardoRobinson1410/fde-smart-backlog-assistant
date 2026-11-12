"""Streamlit interactive workbench with live Scenario Variable customization for FDE demos."""

from __future__ import annotations
import tempfile
from pathlib import Path
import streamlit as st
from backlog_assistant.config import load_scenario_config
from backlog_assistant.engine import BacklogEngine
from backlog_assistant.parser import load_existing_backlog

st.set_page_config(page_title="FDE Smart Backlog Assistant", layout="wide")


def render_app() -> None:
    st.sidebar.header("1. Scenario Preset & Variables")
    presets = {
        "Default: Smart Backlog Assistant": "config/scenario_config.json",
        "Preset 2: SRE Incident Triage Assistant": "config/presets/incident_triage_scenario.json",
    }
    base_cfg = load_scenario_config(presets[st.sidebar.selectbox("Select Scenario Preset", list(presets.keys()))])
    cfg = base_cfg.with_overrides({
        "domain_name": st.sidebar.text_input("Domain Name (`domain_name`)", value=base_cfg.domain_name),
        "agent_role": st.sidebar.text_input("Agent Persona (`agent_role`)", value=base_cfg.agent_role),
        "output_item_label": st.sidebar.text_input("Output Item Label (`output_item_label`)", value=base_cfg.output_item_label),
        "id_prefix": st.sidebar.text_input("ID Prefix (`id_prefix`)", value=base_cfg.id_prefix),
        "subagent_models.extractor_agent": st.sidebar.text_input("Extractor Model (Cheap/Fast)", value=base_cfg.subagent_models.extractor_agent),
        "subagent_models.backlog_auditor": st.sidebar.text_input("Auditor Model (Cheap/Fast)", value=base_cfg.subagent_models.backlog_auditor),
        "subagent_models.security_reviewer": st.sidebar.text_input("Security Model (Reasoning)", value=base_cfg.subagent_models.security_reviewer),
    })
    offline = st.sidebar.checkbox("Force Offline Deterministic Mode", value=False)

    st.title(f"⚡ {cfg.project_title}")
    st.caption(f"**Domain**: {cfg.domain_name} | **Persona**: {cfg.agent_role}")

    col_in, col_bl = st.columns([3, 2])
    with col_in:
        samples_dir = Path(cfg.paths.samples_dir)
        sample = st.selectbox("Choose a realistic sample scenario:", sorted(p.name for p in samples_dir.glob("*") if p.suffix.lower() in {".txt", ".md", ".pdf"}))
        uploaded = st.file_uploader("Or upload a custom document (.txt, .md, .pdf):", type=["txt", "md", "pdf"])
    with col_bl:
        st.dataframe([i.model_dump() for i in load_existing_backlog(cfg.paths.baseline_backlog)], use_container_width=True, height=200)

    if st.button(f"Generate & Deduplicate {cfg.output_item_label}s", type="primary"):
        if uploaded:
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded.name).suffix) as tmp:
                tmp.write(uploaded.getvalue())
                target = Path(tmp.name)
        else:
            target = samples_dir / sample
        res = BacklogEngine(config=cfg, force_offline=offline).analyze(target)
        st.success(
            f"Completed in {res.metadata.latency_ms} ms ({res.metadata.execution_mode}) | "
            f"SHA256: `{res.metadata.document_sha256}` | PII Redacted: {res.metadata.pii_redacted_count} | "
            f"Est. Cost: ${res.metadata.estimated_cost_usd:.6f}"
        )
        st.write(res.summary.executive_summary)
        for s in res.stories:
            hitl_badge = " ⚠️ [HITL APPROVAL REQUIRED]" if s.requires_human_approval else ""
            with st.expander(f"{s.id} | [{s.backlog_alignment.value}] {s.title} — {s.priority} ({s.story_points} pts){hitl_badge}", expanded=True):
                st.markdown(f"**{cfg.output_item_label}:** *{s.user_story}*\n\n**Context:** {s.technical_description}\n\n**Acceptance Criteria:**\n" + "\n".join(f"- [x] {ac}" for ac in s.acceptance_criteria))
        c1, c2 = st.columns(2)
        c1.download_button("Download JSON", res.model_dump_json(indent=2), file_name="result.json")
        c2.download_button("Download Markdown", res.to_markdown(cfg), file_name="report.md")


if __name__ == "__main__":
    render_app()
