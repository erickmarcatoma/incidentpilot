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

def test_missing_telemetry_cannot_be_ok():
    # Case 3: metrics and traces are empty, so code must not call the diagnosis ok
    packet, report = report_for_case1()
    packet = packet.model_copy(update={"metrics": [], "traces": []})

    result = validate_report(packet, report)

    assert result.status is DiagnosisStatus.UNCERTAIN
    assert any("metrics, traces unavailable" in note for note in result.validation_notes)

def test_blaming_a_service_without_its_evidence_cannot_be_ok():
    # H1 blames payment, but its only evidence is a checkout log
    packet, report = report_for_case1()
    checkout_log = next(
        e for e in packet.logs if e.service == "checkout" and e.severity == "error"
    )
    report["hypotheses"][0]["evidence"] = [
        {"source": "logs", "ref": checkout_log.ref, "quote": "Invalid token."}
    ]

    result = validate_report(packet, report)

    assert result.status is DiagnosisStatus.UNCERTAIN
    assert any("none of its evidence comes from payment" in n for n in result.validation_notes)


# --- Red-team finding A1: evidence must be specific -------------------------

def _with_quote(source, ref, quote):
    packet, report = report_for_case1()
    report["hypotheses"][0]["evidence"] = [{"source": source, "ref": ref, "quote": quote}]
    return packet, report


@pytest.mark.parametrize("quote", ["a", ".", "Invalid", "token."])
def test_trivial_log_quotes_are_rejected(quote):
    packet, report = report_for_case1()
    ref = report["hypotheses"][0]["evidence"][0]["ref"]
    packet, report = _with_quote("logs", ref, quote)

    result = validate_report(packet, report)

    assert result.status is DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert any("too short" in note for note in result.validation_notes)


def test_exact_metric_value_is_valid_evidence():
    packet, _ = report_for_case1()
    series = next(s for s in packet.metrics if s.ref == "metric:payment:error_rate")
    value = repr(series.points[-1].value)
    packet, report = _with_quote("metrics", series.ref, value)

    assert validate_report(packet, report).hypotheses


def test_metric_number_not_in_the_series_is_rejected():
    # "85.0" is in the evidence text (as the baseline) but is not a measured point
    packet, _ = report_for_case1()
    series = next(s for s in packet.metrics if s.ref == "metric:payment:latency_p95_ms")
    assert 85.0 not in {p.value for p in series.points}
    packet, report = _with_quote("metrics", series.ref, "85.0")

    assert validate_report(packet, report).status is DiagnosisStatus.INSUFFICIENT_EVIDENCE
