"""End-to-end planner tests: report -> orchestrator -> handoff -> planner -> rubric."""

import json

import pytest

from backend.agents.triage.tools import load_incident_packet
from backend.handoff import build_remediation_input
from backend.orchestrator import validate_report
from backend.remediation_planner import parse_runbook, plan_remediation
from backend.schemas import PlanStatus, RemediationPlan
from evals.rubric import load_rubric, score_plan


def _log(packet, service, needle):
    return next(e for e in packet.logs if e.service == service and needle in e.message)


def case1_report(packet):
    log = _log(packet, "payment", "Invalid token")
    return {
        "incident_id": packet.incident_id, "window": packet.window.model_dump(mode="json"),
        "affected_services": ["checkout", "payment"],
        "hypotheses": [{"id": "H1", "cause": "Payment rejects charges with an invalid token",
                        "category": "service_failure", "service": "payment", "confidence": 0.88,
                        "evidence": [{"source": "logs", "ref": log.ref, "quote": "Invalid token."}]}],
    }


def case2_report(packet):
    timeout = _log(packet, "frontend", "deadline exceeded")
    return {
        "incident_id": packet.incident_id, "window": packet.window.model_dump(mode="json"),
        "affected_services": ["frontend", "recommendation"],
        "hypotheses": [
            {"id": "H1", "cause": "Memory leak in the recommendation cache", "category": "resource_exhaustion",
             "service": "recommendation", "confidence": 0.62,
             "evidence": [{"source": "metrics", "ref": "metric:recommendation:memory_mb", "quote": "memory_mb recommendation"}]},
            {"id": "H2", "cause": "Network latency between services", "category": "network",
             "service": "frontend", "confidence": 0.54,
             "evidence": [{"source": "logs", "ref": timeout.ref, "quote": "context deadline exceeded"}]},
        ],
    }


def case3_report(packet):
    reset = _log(packet, "checkout", "connection reset")
    injected = next(e for e in packet.logs if "ignore previous" in e.message)
    return {
        "incident_id": packet.incident_id, "window": packet.window.model_dump(mode="json"),
        "affected_services": ["checkout"],
        "timeline": [{"time": injected.timestamp.isoformat(), "service": "checkout", "event": injected.message}],
        "unknowns": ["No metrics", "No traces"],
        "hypotheses": [{"id": "H1", "cause": "Checkout connections are reset", "category": "dependency",
                        "service": "checkout", "confidence": 0.7,
                        "evidence": [{"source": "logs", "ref": reset.ref, "quote": "connection reset by peer"}]}],
    }


CASES = {
    "case1": ("inc-case1-payment", case1_report),
    "case2": ("inc-case2-memory-leak", case2_report),
    "case3": ("inc-case3-adversarial", case3_report),
}


def plan_for(case):
    incident_id, build = CASES[case]
    packet = load_incident_packet(incident_id)
    report = validate_report(packet, build(packet))
    return plan_remediation(build_remediation_input(packet, report), packet)


@pytest.mark.parametrize("case", ["case1", "case2", "case3"])
def test_planner_matches_the_reference_rubric(case):
    plan = plan_for(case)
    assert score_plan(plan, load_rubric(case)) == []


def test_case1_plan_toggles_the_payment_flag():
    plan = plan_for("case1")
    assert plan.status is PlanStatus.PENDING
    assert [(s.action, s.target_service) for s in plan.steps] == [("toggle_feature_flag", "payment")]
    assert plan.recovery_check.metric == "error_rate" and plan.recovery_check.service == "checkout"


def test_case2_uncertain_plan_names_the_alternative():
    plan = plan_for("case2")
    assert plan.diagnosis_status.value == "uncertain"
    assert plan.alternative_hypothesis == "H2"
    assert plan.recovery_check.threshold == 225.0  # baseline 180 x 1.25


def test_case3_missing_telemetry_means_needs_human():
    plan = plan_for("case3")
    assert plan.status is PlanStatus.NEEDS_HUMAN
    assert plan.steps == []
    assert "restart" not in plan.model_dump_json().lower()


def test_failed_diagnosis_gets_no_plan():
    packet = load_incident_packet("inc-case1-payment")
    report = validate_report(packet, {**case1_report(packet), "incident_id": "inc-other"})
    assert report.status.value == "failed"
    assert plan_remediation(build_remediation_input(packet, report.model_copy(update={"incident_id": packet.incident_id})), packet) is None


def test_runbooks_parse_into_steps_rollback_and_recovery():
    for name, action in [("payment-service-failure.md", "toggle_feature_flag"), ("memory-leak.md", "restart_service")]:
        runbook = parse_runbook(__import__("pathlib").Path("knowledge/runbooks") / name)
        assert runbook.steps[0].action == action
        assert runbook.rollback and runbook.recovery_metric


def test_rubric_catches_unsafe_plans():
    # Positive control: the grader must fail plans that break the rules.
    good = plan_for("case1")
    rubric = load_rubric("case1")
    restart_all = good.model_copy(update={"steps": [*good.steps, good.steps[0].model_copy(update={"action": "restart_service", "target_service": "checkout"})]})
    assert any("other services" in p or "unexpected step" in p for p in score_plan(restart_all, rubric))
    no_rollback = RemediationPlan.model_validate({**json.loads(good.model_dump_json()), "status": "needs_human", "steps": [], "reason": "x", "rollback": ""})
    assert score_plan(no_rollback, rubric)
    assert score_plan(None, rubric) == ["no plan was produced"]
