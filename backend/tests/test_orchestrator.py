import pytest
from pydantic import ValidationError

from backend.agents.triage.tools import load_incident_packet
from backend.orchestrator import validate_report
from backend.schemas import DiagnosisStatus


def report_for_case1(**overrides):
    packet = load_incident_packet("inc-payment-001")
    report = {
        "incident_id": packet.incident_id,
        "window": packet.window.model_dump(mode="json"),
        "affected_services": ["checkout", "payment"],
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
                        "ref": "log:payment-001",
                        "quote": "invalid token",
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
    packet, report = report_for_case1(
        hypotheses=[
            {
                **report_for_case1()[1]["hypotheses"][0],
                "evidence": [
                    {
                        "source": "logs",
                        "ref": "log:payment-001",
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


def test_multiple_supported_hypotheses_are_uncertain():
    packet, report = report_for_case1(
        hypotheses=[
            report_for_case1()[1]["hypotheses"][0],
            {
                "id": "H2",
                "cause": "Checkout failed after payment returned an error",
                "category": "dependency",
                "service": "checkout",
                "confidence": 0.7,
                "evidence": [
                    {
                        "source": "logs",
                        "ref": "log:checkout-001",
                        "quote": "payment authorization returned 401",
                    }
                ],
            },
        ]
    )

    result = validate_report(packet, report)

    assert result.status is DiagnosisStatus.UNCERTAIN
    assert [hypothesis.id for hypothesis in result.hypotheses] == ["H1", "H2"]


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