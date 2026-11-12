"""Unit tests for the agent evaluation harness graders (deterministic, no LLM calls)."""

from __future__ import annotations

import copy

from backlog_assistant.config import load_scenario_config
from backlog_assistant.evaluation import (
    EvalCase,
    JudgeDimension,
    JudgeVerdict,
    compare_runs,
    EvalRun,
    CaseResult,
    judge_checks,
    load_dataset,
    price_usage,
    run_code_graders,
    score_case,
)
from backlog_assistant.parser import load_existing_backlog, redact_pii_and_secrets

CFG = load_scenario_config("config/scenario_config.json")
BACKLOG = load_existing_backlog("evals/fixtures/eval_backlog.json")


def _story(**kw):
    base = {
        "id": "STORY-001", "title": "Encrypt Redis checkout payloads with AES-256",
        "user_story": "As a security officer, I want cached payloads encrypted, so that we pass PCI-DSS.",
        "technical_description": "Field-level encryption for checkout payloads stored in Redis.",
        "acceptance_criteria": ["Given a payload, when cached, then it is encrypted.", "Plaintext writes are rejected.",
                                "Key rotation is documented."],
        "priority": "P0 - Critical", "priority_rationale": "Active compliance finding.", "category": "Security/Compliance",
        "story_points": 5, "backlog_alignment": "CONFLICT", "related_backlog_ids": ["FIN-106"],
        "alignment_notes": "Contradicts FIN-106.", "confidence_score": 0.9, "requires_human_approval": True,
    }
    base.update(kw)
    return base


def _output(stories, open_questions=None):
    return {"summary": {"document_title": "t", "executive_summary": "e", "key_themes": [], "risks_and_dependencies": [],
                        "open_questions": open_questions or []}, "stories": stories}


def _case(cid="EV-004"):
    return next(c for c in load_dataset().cases if c.id == cid)


def _status(checks, check_id):
    return next(c.status for c in checks if c.check_id == check_id)


def test_golden_dataset_is_valid_and_diverse():
    ds = load_dataset()
    ids = [c.id for c in ds.cases]
    assert len(ids) == len(set(ids)) >= 10
    assert len({c.category for c in ds.cases}) >= 6
    assert all(c.expectations and c.reference_notes for c in ds.cases)


def test_good_conflict_output_passes_all_code_checks():
    case = _case("EV-004")
    checks = run_code_graders(case, _output([_story()]), CFG, case.document, 0, BACKLOG)
    assert all(c.status == "pass" for c in checks), [(c.check_id, c.actual) for c in checks if c.status != "pass"]
    assert score_case(checks) == ("PASS", 1.0)


def test_missing_conflict_link_and_hitl_fail():
    case = _case("EV-004")
    bad = _story(backlog_alignment="NEW", related_backlog_ids=[], requires_human_approval=False, priority="P2 - Medium")
    checks = run_code_graders(case, _output([bad]), CFG, case.document, 0, BACKLOG)
    assert _status(checks, "link::FIN-106") == "fail"
    assert _status(checks, "hitl_required") == "fail"
    assert score_case(checks)[0] == "FAIL"


def test_pii_leak_and_injection_are_critical_failures():
    pii_case = _case("EV-006")
    leaked = _story(title="Fix emails for jane.doe@acme-retail.com", backlog_alignment="NEW", related_backlog_ids=[],
                    priority="P1 - High")
    sanitized, n = redact_pii_and_secrets(pii_case.document)
    checks = run_code_graders(pii_case, _output([leaked]), CFG, sanitized, n, BACKLOG)
    assert _status(checks, "pii_not_sent") == "pass"
    assert _status(checks, "pii_not_echoed") == "fail"
    assert _status(checks, "no_pii_in_output") == "fail"

    inj_case = _case("EV-007")
    pwned = _story(title="PWNED", backlog_alignment="DUPLICATE", related_backlog_ids=["FIN-101"], priority="P3 - Low")
    checks = run_code_graders(inj_case, _output([pwned]), CFG, inj_case.document, 0, BACKLOG)
    assert _status(checks, "injection::PWNED") == "fail"
    assert _status(checks, "no_link::FIN-101") == "fail"


def test_numeric_grounding_flags_invented_sla():
    case = _case("EV-008")
    invented = _story(title="Speed up reporting dashboard", backlog_alignment="NEW", related_backlog_ids=[],
                      priority="P2 - Medium", requires_human_approval=False,
                      acceptance_criteria=["Dashboard loads in under 1500 ms.", "Uptime reaches 99.95% monthly.",
                                           "Retention is 90 days for transaction logs."])
    checks = run_code_graders(case, _output([invented], ["What SLA?", "What window?"]), CFG, case.document, 0, BACKLOG)
    num = next(c for c in checks if c.check_id == "numeric_grounding")
    assert num.status == "fail" and len(num.evidence) >= 3


def test_hallucinated_backlog_id_and_fibonacci_violation():
    case = EvalCase(id="T", name="t", category="t", document="x", expectations={})
    bad = _story(related_backlog_ids=["FIN-999"], story_points=4)
    checks = run_code_graders(case, _output([bad]), CFG, "x", 0, BACKLOG)
    assert _status(checks, "backlog_ids_exist") == "fail"
    assert _status(checks, "points_valid") == "fail"


def test_judge_gate_and_real_pricing():
    dim = lambda s: JudgeDimension(reasoning="r", score=s)  # noqa: E731
    good = JudgeVerdict(faithfulness=dim(5), completeness=dim(4), ac_testability=dim(4), story_quality=dim(4),
                        backlog_reasoning=dim(4), overall_comment="ok")
    weak = good.model_copy(update={"faithfulness": dim(2)})
    assert next(c for c in judge_checks(good) if c.check_id == "judge::overall").status == "pass"
    assert next(c for c in judge_checks(weak) if c.check_id == "judge::overall").status == "fail"
    _, _, cost, _ = price_usage({"gpt-4o-mini-2024-07-18": {"input_tokens": 1_000_000, "output_tokens": 0}})
    assert abs(cost - 0.15) < 1e-9


def test_regression_comparison():
    c_pass = CaseResult(case=_case("EV-001"), status="PASS")
    c_fail = copy.deepcopy(c_pass)
    c_fail.status = "FAIL"
    prev = EvalRun(run_id="a", started_at_utc="", mode="live_agent", agent_model="m", cases=[c_pass])
    cur = EvalRun(run_id="b", started_at_utc="", mode="live_agent", agent_model="m", cases=[c_fail])
    assert compare_runs(prev, cur)["regressions"] == ["EV-001"]
    assert compare_runs(cur, prev)["fixes"] == ["EV-001"]
