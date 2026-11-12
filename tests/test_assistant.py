"""Automated pytest verification suite for the Configurable FDE Smart Backlog Assistant."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from backlog_assistant.config import load_scenario_config
from backlog_assistant.engine import BacklogEngine
from backlog_assistant.models import BacklogAlignment, GeneratedUserStory
from backlog_assistant.parser import extract_document_text, load_existing_backlog
from backlog_assistant.prompts import build_system_prompt


def test_scenario_config_and_dynamic_variable_overrides() -> None:
    """Verify ScenarioConfig loads defaults and adapts when variables are modified."""
    base_cfg = load_scenario_config("config/scenario_config.json")
    assert base_cfg.scenario_id == "smart_backlog_assistant"
    assert base_cfg.id_prefix == "STORY"

    # Modify variables dynamically to adapt to a new client scenario
    adapted_cfg = base_cfg.with_overrides({
        "scenario_id": "healthcare_claims_triage",
        "domain_name": "Healthcare Claims & HIPAA Engineering",
        "id_prefix": "HIPAA",
        "output_item_label": "Compliance Task",
    })
    assert adapted_cfg.domain_name == "Healthcare Claims & HIPAA Engineering"
    assert adapted_cfg.id_prefix == "HIPAA"

    # Prompt must dynamically incorporate the overridden variables
    sys_prompt = build_system_prompt(adapted_cfg)
    assert "Healthcare Claims & HIPAA Engineering" in sys_prompt
    assert "HIPAA-001" in sys_prompt
    assert "Compliance Task" in sys_prompt


def test_document_parser_txt_md_pdf_and_error_handling(tmp_path: Path) -> None:
    """Verify extraction across .txt, .md, and .pdf plus clean error handling."""
    txt_text = extract_document_text("data/samples/01_sprint_planning_notes.txt")
    md_text = extract_document_text("data/samples/02_incident_postmortem.md")
    pdf_text = extract_document_text("data/samples/03_pci_compliance_spec.pdf")

    assert "Enterprise SSO" in txt_text
    assert "SEV-1" in md_text
    assert "PCI-DSS" in pdf_text

    # Error handling: missing file, unsupported format, and empty file
    with pytest.raises(FileNotFoundError):
        extract_document_text(tmp_path / "missing.txt")

    bad_ext = tmp_path / "notes.docx"
    bad_ext.write_text("content", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported file format"):
        extract_document_text(bad_ext)

    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("   \n  ", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        extract_document_text(empty_file)


def test_pydantic_guardrail_rejects_fewer_than_three_acceptance_criteria() -> None:
    """Verify Pydantic schema guardrail blocks stories with < 3 testable acceptance criteria."""
    with pytest.raises(ValidationError):
        GeneratedUserStory(
            id="STORY-001",
            title="Incomplete Story",
            user_story="As a user, I want X, so that Y",
            technical_description="Details",
            acceptance_criteria=["Only one criterion", "Only two criteria"],
            priority="P1 - High",
            priority_rationale="High priority",
            category="Feature",
            story_points=3,
            backlog_alignment=BacklogAlignment.NEW,
        )


def test_golden_scenarios_deduplication_and_conflict_detection() -> None:
    """Verify all 3 sample scenarios produce expected NEW, DUPLICATE, UPDATES_EXISTING, and CONFLICT flags."""
    engine = BacklogEngine(force_offline=True)

    # Scenario 1: Sprint Planning Notes -> NEW + DUPLICATE (FIN-101) + UPDATES_EXISTING (FIN-104)
    res1 = engine.analyze("data/samples/01_sprint_planning_notes.txt")
    alignments_1 = {s.backlog_alignment for s in res1.stories}
    assert BacklogAlignment.NEW in alignments_1
    assert BacklogAlignment.DUPLICATE in alignments_1
    assert BacklogAlignment.UPDATES_EXISTING in alignments_1
    assert any("FIN-101" in s.related_backlog_ids for s in res1.stories if s.backlog_alignment == BacklogAlignment.DUPLICATE)

    # Scenario 2: Incident Postmortem -> NEW + UPDATES_EXISTING (FIN-105)
    res2 = engine.analyze("data/samples/02_incident_postmortem.md")
    assert any("FIN-105" in s.related_backlog_ids for s in res2.stories)
    assert all(len(s.acceptance_criteria) >= 3 for s in res2.stories)

    # Scenario 3: PCI Compliance PDF -> CONFLICT (FIN-106) + NEW
    res3 = engine.analyze("data/samples/03_pci_compliance_spec.pdf")
    assert any(
        s.backlog_alignment == BacklogAlignment.CONFLICT and "FIN-106" in s.related_backlog_ids
        for s in res3.stories
    )


def test_custom_scenario_preset_and_ad_hoc_document(tmp_path: Path) -> None:
    """Verify switching to the SRE Incident Triage preset adapts IDs and categories on custom files."""
    sre_cfg = load_scenario_config("config/presets/incident_triage_scenario.json")
    engine = BacklogEngine(config=sre_cfg, force_offline=True)

    custom_doc = tmp_path / "custom_outage_notes.txt"
    custom_doc.write_text(
        "Database Read-Replica Lag Alerting\n"
        "PostgreSQL read-replica routing for reporting queries experienced 45s replication lag during settlement.\n\n"
        "Automated Runbook for Cache Eviction\n"
        "Need an automated SRE script to flush stale Redis keys safely with rate limiting.",
        encoding="utf-8",
    )
    res = engine.analyze(custom_doc)
    assert res.stories[0].id == "REM-001"
    assert res.stories[0].category in sre_cfg.categories
    assert "REM-103" in res.stories[0].related_backlog_ids  # Matched REM-103 in isolated incident_triage_backlog.json


def test_pre_tool_use_hook_contract() -> None:
    """Verify the PreToolUse lifecycle hook script adheres to the camelCase stdin/stdout JSON contract."""
    safe_input = json.dumps({"toolCall": {"id": "1", "name": "run_command", "args": {"CommandLine": "pytest -q"}}})
    proc_safe = subprocess.run(
        [sys.executable, "scripts/hooks/pre_tool_gate.py"],
        input=safe_input,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(proc_safe.stdout)["decision"] == "allow"

    unsafe_input = json.dumps({"toolCall": {"id": "2", "name": "run_command", "args": {"CommandLine": "git push --force"}}})
    proc_unsafe = subprocess.run(
        [sys.executable, "scripts/hooks/pre_tool_gate.py"],
        input=unsafe_input,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(proc_unsafe.stdout)["decision"] == "deny"


def test_langgraph_multi_agent_state_graph_and_mermaid() -> None:
    """Verify the compiled LangGraph StateGraph executes all 4 agent nodes and generates a Mermaid diagram."""
    engine = BacklogEngine(force_offline=True)
    mermaid_str = engine.get_graph_mermaid()
    assert "ingest_node" in mermaid_str
    assert "extractor_agent" in mermaid_str
    assert "backlog_auditor" in mermaid_str
    assert "security_reviewer" in mermaid_str

    result = engine.analyze("data/samples/01_sprint_planning_notes.txt")
    assert result.metadata.agent_trace == [
        "ingest_node",
        "extractor_agent",
        "backlog_auditor",
        "security_reviewer",
    ]
    assert result.metadata.subagent_models_used == {
        "extractor_agent": "gpt-4o-mini",
        "backlog_auditor": "gpt-4o-mini",
        "security_reviewer": "gpt-4o",
    }

    # Verify per-subagent cost-optimization overrides work dynamically
    custom_cfg = load_scenario_config().with_overrides({
        "subagent_models.extractor_agent": "gpt-4o-mini",
        "subagent_models.security_reviewer": "gpt-4o-mini",
    })
    res_custom = BacklogEngine(config=custom_cfg, force_offline=True).analyze("data/samples/01_sprint_planning_notes.txt")
    assert res_custom.metadata.subagent_models_used["security_reviewer"] == "gpt-4o-mini"


def test_fde_guardrails_pii_redaction_finops_hitl_and_audit_log(tmp_path: Path) -> None:
    """Verify the 5 enterprise FDE guardrails: PII scrubbing, SHA256, FinOps cost, HITL gate, and audit_trail.jsonl."""
    from backlog_assistant.parser import redact_pii_and_secrets

    # 1. Pre-LLM PII & Secret Redaction
    dirty_text = "Contact alice@client.com or use token sk-proj-1234567890abcdefghijklmnop and card 4111 2222 3333 4444."
    scrubbed, pii_count = redact_pii_and_secrets(dirty_text)
    assert pii_count == 3
    assert "[REDACTED_EMAIL]" in scrubbed
    assert "[REDACTED_SECRET]" in scrubbed
    assert "[REDACTED_PAN]" in scrubbed
    assert "alice@client.com" not in scrubbed

    # 2. Run engine with custom audit log path and verify SHA-256, HITL gate on P0/CONFLICT, and JSONL audit log
    audit_file = tmp_path / "audit_trail.jsonl"
    cfg = load_scenario_config().with_overrides({"paths.audit_log_path": str(audit_file)})
    engine = BacklogEngine(config=cfg, force_offline=True)
    res_pci = engine.analyze("data/samples/03_pci_compliance_spec.pdf")

    assert len(res_pci.metadata.document_sha256) == 16
    assert res_pci.metadata.estimated_tokens > 0
    # STORY-001 in PCI spec is P0-Critical & CONFLICT -> must trigger HITL approval gate
    assert res_pci.stories[0].requires_human_approval is True
    assert res_pci.stories[1].requires_human_approval is False

    # Verify append-only JSONL compliance audit log was written
    assert audit_file.exists()
    logged = json.loads(audit_file.read_text(encoding="utf-8").splitlines()[-1])
    assert logged["document_sha256"] == res_pci.metadata.document_sha256
    assert logged["hitl_approval_required_count"] == 1

    # Verify the Centralized FDE Portal audit history loader reads the JSONL records
    from backlog_assistant.app import load_audit_history

    portal_records = load_audit_history(audit_file)
    assert len(portal_records) == 1
    assert portal_records[0]["document_sha256"] == res_pci.metadata.document_sha256


def test_task_crud_and_hitl_risk_policy(tmp_path: Path) -> None:
    """Verify agent Task CRUD (create/update/move/delete) and HITL gating for critical operations."""
    from backlog_assistant.app import _classify_task_action_risk, _execute_task_action
    from backlog_assistant.models import ExistingBacklogItem
    from backlog_assistant.parser import save_existing_backlog

    backlog_file = tmp_path / "existing_backlog.json"
    audit_file = tmp_path / "audit_trail.jsonl"
    save_existing_backlog(
        [
            ExistingBacklogItem(id="FIN-101", title="OAuth2 Login", status="Open", priority="P1 - High", category="Auth", summary="Base"),
            ExistingBacklogItem(id="FIN-104", title="Legacy 3DES", status="In Progress", priority="P2 - Medium", category="Security", summary="Legacy"),
        ],
        backlog_file,
    )
    cfg = load_scenario_config().with_overrides({
        "paths.baseline_backlog": str(backlog_file),
        "paths.audit_log_path": str(audit_file),
    })

    # 1. Critical operations must require HITL approval
    hitl_del, _ = _classify_task_action_risk({"op": "delete", "id": "FIN-101"}, [])
    hitl_p0, _ = _classify_task_action_risk({"op": "create", "title": "Emergency Fix", "priority": "P0 - Critical"}, [])
    hitl_done, _ = _classify_task_action_risk({"op": "move", "id": "FIN-101", "status": "Done"}, [])
    hitl_sec, _ = _classify_task_action_risk({"op": "move", "id": "FIN-104", "status": "In Progress"}, [])
    assert hitl_del and hitl_p0 and hitl_done and hitl_sec

    # 2. Task creation also requires HITL approval before persisting; non-critical In Progress move is auto-approved
    hitl_create, _ = _classify_task_action_risk({"op": "create", "title": "Update Docs", "priority": "P2 - Medium"}, [])
    assert hitl_create is True
    hitl_move_low, _ = _classify_task_action_risk({"op": "move", "id": "FIN-101", "status": "In Progress"}, [])
    assert hitl_move_low is False
    res_create = _execute_task_action({"op": "create", "title": "Update Docs", "priority": "P2 - Medium"}, cfg, approved_by_human=True)
    assert res_create["ok"] is True
    assert res_create["ticket"]["id"] == "FIN-105"

    # 3. Move & Delete execute after human approval and emit audit trail
    res_move = _execute_task_action({"op": "move", "id": "FIN-105", "status": "In Progress"}, cfg, approved_by_human=True)
    assert res_move["ok"] and res_move["ticket"]["status"] == "In Progress"
    res_del = _execute_task_action({"op": "delete", "id": "FIN-105"}, cfg, approved_by_human=True)
    assert res_del["ok"]
    assert len(load_existing_backlog(backlog_file)) == 2
    assert len(audit_file.read_text(encoding="utf-8").splitlines()) == 3


def test_memory_bank_and_natural_language_task_intent(tmp_path: Path, monkeypatch) -> None:
    """Verify FDE Memory Bank persistence and natural-language task creation intent detection."""
    import backlog_assistant.app as app_mod

    mem_file = tmp_path / "memory_bank.json"
    monkeypatch.setattr(app_mod, "MEMORY_BANK_PATH", mem_file)
    cfg = load_scenario_config().with_overrides({
        "paths.audit_log_path": str(tmp_path / "audit_trail.jsonl"),
    })

    # 1. Capability question should NOT be misclassified as a task creation command
    cap_intent = app_mod._detect_task_action_intent("can you create a new task now?", [], None)
    assert cap_intent is None

    # 2. Natural-language creation request MUST be classified as a create command
    create_intent = app_mod._detect_task_action_intent(
        "I need a new task for creating a monitoring center", [], None
    )
    assert create_intent is not None
    assert create_intent["op"] == "create"
    assert "monitoring center" in create_intent["title"].lower()

    # 2b. Generic "create a new task" asks for details; detailed request triggers HITL approval
    bundle = app_mod.build_all_scenarios_bundle(cfg)
    bl = [b.model_dump() for b in app_mod.load_existing_backlog(cfg.paths.baseline_backlog)]
    r_generic = app_mod._answer_with_live_openai_or_analytical_engine("create a new task", [], None, bundle, bl, cfg)
    assert r_generic["type"] == "conversation"
    assert "please share the details" in r_generic["replyHtml"].lower()
    r_detailed = app_mod._answer_with_live_openai_or_analytical_engine(
        "I need a new task for creating a monitoring center", [], None, bundle, bl, cfg
    )
    assert r_detailed["type"] == "hitl_action"

    # 3. Memory bank persists decisions and recent turns
    app_mod.update_memory_bank(
        cfg,
        decision="Created FIN-107 (Monitoring center)",
        user_turn="I need a new task for creating a monitoring center",
        assistant_turn="Created FIN-107.",
    )
    mb = app_mod.load_memory_bank(cfg)
    assert any("FIN-107" in d.get("decision", "") for d in mb.get("recent_decisions", []))
    assert len(mb.get("session_turns", [])) >= 1







