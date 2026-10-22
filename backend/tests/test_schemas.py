from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from backend.schemas import (
    DiagnosisStatus,
    EvidenceSource,
    IncidentPacket,
    PlanStatus,
    RemediationPlan,
    RootCauseReport,
)

T0 = datetime(2026, 10, 22, 14, 0, tzinfo=timezone.utc)
WINDOW = {"start": T0, "end": T0 + timedelta(minutes=15)}


def hypothesis(hid="H1", confidence=0.8, **overrides):
    data = {
        "id": hid,
        "cause": "Payment service returns errors after a bad feature flag",
        "category": "service_failure",
        "service": "payment",
        "confidence": confidence,
        "evidence": [{"source": "logs", "ref": "log:001", "quote": "payment failed: invalid token"}],
    }
    data.update(overrides)
    return data


def report(**overrides):
    data = {
        "incident_id": "inc-001",
        "window": WINDOW,
        "affected_services": ["checkout", "payment"],
        "hypotheses": [hypothesis()],
    }
    data.update(overrides)
    return data


def plan(**overrides):
    data = {
        "incident_id": "inc-001",
        "addresses_hypothesis": "H1",
        "runbook": {"file": "payment-service-failure.md", "section": "Bad feature flag"},
        "steps": [{"action": "disable_feature_flag", "target_service": "payment", "policy_result": "requires_approval"}],
        "rollback": "Re-enable the flag",
        "recovery_check": {"metric": "checkout_error_rate", "service": "checkout", "threshold": 0.02},
        "incident_summary": "Checkout errors rose above 20% after the paymentFailure flag was enabled.",
        "diagnosis_status": "ok",
    }
    data.update(overrides)
    return data


def test_valid_report_and_plan():
    r = RootCauseReport.model_validate(report())
    assert r.status is None  # only the orchestrator sets it
    p = RemediationPlan.model_validate(plan())
    assert p.status is PlanStatus.PENDING


def test_unknown_category_rejected():
    with pytest.raises(ValidationError):
        RootCauseReport.model_validate(report(hypotheses=[hypothesis(category="cosmic_rays")]))


def test_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        RootCauseReport.model_validate(report(hypotheses=[hypothesis(confidence=1.4)]))


def test_hypotheses_must_be_sorted_and_unique():
    with pytest.raises(ValidationError):
        RootCauseReport.model_validate(report(hypotheses=[hypothesis("H1", 0.3), hypothesis("H2", 0.7)]))
    with pytest.raises(ValidationError):
        RootCauseReport.model_validate(report(hypotheses=[hypothesis("H1", 0.7), hypothesis("H1", 0.3)]))


def test_at_most_three_hypotheses():
    many = [hypothesis(f"H{i}", 0.9 - i / 10) for i in (1, 2, 3)] + [hypothesis("H3", 0.1)]
    with pytest.raises(ValidationError):
        RootCauseReport.model_validate(report(hypotheses=many))


def test_hypothesis_needs_evidence():
    with pytest.raises(ValidationError):
        RootCauseReport.model_validate(report(hypotheses=[hypothesis(evidence=[])]))


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        RootCauseReport.model_validate(report(fix="restart everything"))


def test_plan_cannot_contain_rejected_step():
    step = {"action": "restart_all", "target_service": "*", "policy_result": "rejected"}
    with pytest.raises(ValidationError):
        RemediationPlan.model_validate(plan(steps=[step]))


def test_needs_human_plan_has_no_steps_and_a_reason():
    ok = RemediationPlan.model_validate(
        plan(steps=[], status="needs_human", reason="Metrics and traces unavailable",
             diagnosis_status="insufficient_evidence", addresses_hypothesis=None)
    )
    assert ok.status is PlanStatus.NEEDS_HUMAN
    with pytest.raises(ValidationError):
        RemediationPlan.model_validate(plan(status="needs_human", reason="x"))
    with pytest.raises(ValidationError):
        RemediationPlan.model_validate(plan(steps=[], status="needs_human"))


def test_insufficient_diagnosis_cannot_be_pending():
    with pytest.raises(ValidationError):
        RemediationPlan.model_validate(plan(diagnosis_status="insufficient_evidence"))


def test_evidence_lookup_finds_real_quotes_only():
    packet = IncidentPacket.model_validate({
        "incident_id": "inc-001",
        "alert": {"name": "HighCheckoutErrors", "service": "checkout", "fired_at": T0},
        "window": WINDOW,
        "services": ["checkout", "payment"],
        "logs": [{"ref": "log:001", "timestamp": T0, "service": "payment",
                  "severity": "error", "message": "payment failed: invalid token"}],
    })
    assert "invalid token" in packet.evidence_text(EvidenceSource.LOGS, "log:001")
    assert packet.evidence_text(EvidenceSource.LOGS, "log:999") is None


def test_window_must_be_ordered():
    with pytest.raises(ValidationError):
        RootCauseReport.model_validate(report(window={"start": WINDOW["end"], "end": WINDOW["start"]}))


def test_status_values_match_prd():
    assert {s.value for s in DiagnosisStatus} == {"ok", "uncertain", "insufficient_evidence", "failed"}