import pytest
from pydantic import ValidationError

from backend.agents.triage.tools import load_incident_packet
from backend.orchestrator import validate_report
from backend.schemas import DiagnosisStatus


def report_for_case1(**overrides):
    packet = load_incident_packet("inc-case1-payment")
    payment_log = next(
        entry
        for entry in packet.logs
        if entry.service == "payment" and entry.severity == "error"
    )
    report = {
        "incident_id": packet.incident_id,
        "window": packet.window.model_dump(mode="json"),
        "affected_services": packet.services,
        "hypotheses": [
            {
                "id": "H1",
                "cause": "Payment authorization fails due to an invalid token",
                "category": "service_failure",
                "service": "payment",
                "confidence": 0.9,
                "evidence": [
                    {
                        "source": "logs",
                        "ref": payment_log.ref,
                        "quote": "Invalid token.",
                    }
                ],
            }
        ],
    }
    report.update(overrides)
    return packet, report


def test_valid_report_is_accepted_and_status_is_set_by_orchestrator():
    packet, report = report_for_case1(status="failed")

    result = validate_report(packet, report)

    assert result.status is DiagnosisStatus.OK
    assert result.hypotheses[0].id == "H1"


@pytest.mark.parametrize(
    ("field", "value", "expected_note"),
    [
        ("incident_id", "inc-other", "incident_id does not match"),
        (
            "affected_services",
            ["checkout", "unknown-service"],
            "affected_services contains",
        ),
    ],
)
def test_inconsistent_report_fails(field, value, expected_note):
    packet, report = report_for_case1(**{field: value})

    result = validate_report(packet, report)

    assert result.status is DiagnosisStatus.FAILED
    assert any(expected_note in note for note in result.validation_notes)


def test_hypothesis_with_missing_evidence_is_removed():
    packet, initial_report = report_for_case1()
    hypothesis = initial_report["hypotheses"][0]
    packet, report = report_for_case1(
        hypotheses=[
            {
                **hypothesis,
                "evidence": [
                    {
                        "source": "logs",
                        "ref": hypothesis["evidence"][0]["ref"],
                        "quote": "invented log text",
                    }
                ],
            }
        ]
    )

    result = validate_report(packet, report)

    assert result.status is DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert result.hypotheses == []
    assert any("evidence reference or quote not found" in note for note in result.validation_notes)


def two_hypotheses_report(h2_confidence):
    packet, initial_report = report_for_case1()
    first_hypothesis = initial_report["hypotheses"][0]
    checkout_log = next(
        entry
        for entry in packet.logs
        if entry.service == "checkout" and entry.severity == "error"
    )
    packet, report = report_for_case1(
        hypotheses=[
            first_hypothesis,
            {
                "id": "H2",
                "cause": "Checkout failed after payment returned an error",
                "category": "dependency",
                "service": "checkout",
                "confidence": h2_confidence,
                "evidence": [
                    {
                        "source": "logs",
                        "ref": checkout_log.ref,
                        "quote": "Payment request failed. Invalid token.",
                    }
                ],
            },
        ]
    )

    return validate_report(packet, report)


def test_close_hypotheses_are_uncertain():
    # H1 = 0.9, H2 = 0.8: gap 0.1 is within 0.15
    result = two_hypotheses_report(0.8)

    assert result.status is DiagnosisStatus.UNCERTAIN
    assert [hypothesis.id for hypothesis in result.hypotheses] == ["H1", "H2"]


def test_clear_leader_with_backup_hypothesis_is_ok():
    # H1 = 0.9, H2 = 0.5: gap 0.4, so H1 is a clear leader
    result = two_hypotheses_report(0.5)

    assert result.status is DiagnosisStatus.OK
    assert [hypothesis.id for hypothesis in result.hypotheses] == ["H1", "H2"]


def test_low_top_confidence_is_uncertain():
    packet, initial_report = report_for_case1()
    hypothesis = {**initial_report["hypotheses"][0], "confidence": 0.4}
    packet, report = report_for_case1(hypotheses=[hypothesis])

    result = validate_report(packet, report)

    assert result.status is DiagnosisStatus.UNCERTAIN


def test_malformed_report_is_rejected():
    packet, report = report_for_case1()
    report["unexpected"] = "field"

    with pytest.raises(ValidationError):
        validate_report(packet, report)


def test_empty_hypotheses_are_only_valid_for_insufficient_evidence():
    packet, report = report_for_case1(hypotheses=[])

    with pytest.raises(ValidationError):
        validate_report(packet, report)

    report["status"] = "insufficient_evidence"
    assert validate_report(packet, report).status is DiagnosisStatus.INSUFFICIENT_EVIDENCE