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
        "github.repo": "RicardoRobinson1410/custom-repo",
    })
    assert adapted_cfg.domain_name == "Healthcare Claims & HIPAA Engineering"
    assert adapted_cfg.id_prefix == "HIPAA"
    assert adapted_cfg.github.repo == "RicardoRobinson1410/custom-repo"

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
    assert "FIN-103" in res.stories[0].related_backlog_ids  # Matched PostgreSQL Read-Replica in existing_backlog.json


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


def test_github_pat_live_backlog_test_case() -> None:
    """Verify live GitHub PAT backlog ingestion & deduplication against RicardoRobinson1410/fde-smart-backlog-assistant."""
    from backlog_assistant.parser import _resolve_github_pat

    token = _resolve_github_pat()
    if not token:
        pytest.skip("No GitHub PAT configured in environment or gh CLI")

    repo = "RicardoRobinson1410/fde-smart-backlog-assistant"
    live_items = load_existing_backlog(backlog_path=None, github_repo=repo)
    assert len(live_items) >= 6
    live_ids = {item.id for item in live_items}
    assert {"FIN-101", "FIN-102", "FIN-104"}.issubset(live_ids)

    # Run BacklogEngine using ONLY the live GitHub repository's Issues as the baseline backlog
    cfg = load_scenario_config().with_overrides({"github.enabled": True, "github.repo": repo})
    engine = BacklogEngine(config=cfg, force_offline=True)
    res = engine.analyze("data/samples/01_sprint_planning_notes.txt", backlog_path="", github_repo=repo)
    assert res.metadata.existing_backlog_count >= 6
    assert any(s.backlog_alignment == BacklogAlignment.DUPLICATE and "FIN-101" in s.related_backlog_ids for s in res.stories)


