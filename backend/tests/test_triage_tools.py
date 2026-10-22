import pytest

from backend.agents.triage.tools import (
    get_metrics,
    get_traces,
    load_incident_packet,
    search_logs,
)
from backend.schemas import EvidenceSource


INCIDENT_IDS = (
    "inc-payment-001",
    "inc-recommendation-002",
    "inc-adversarial-003",
)


@pytest.mark.parametrize("incident_id", INCIDENT_IDS)
def test_fixture_packets_validate(incident_id):
    packet = load_incident_packet(incident_id)
    assert packet.incident_id == incident_id
    assert packet.services


def test_tools_return_refs_and_exact_evidence_text():
    packet = load_incident_packet("inc-payment-001")

    metrics = get_metrics(packet.incident_id)
    logs = search_logs(packet.incident_id)
    traces = get_traces(packet.incident_id)

    for result in metrics:
        assert result["evidence_text"] == packet.evidence_text(
            EvidenceSource.METRICS, result["ref"]
        )
    for result in logs:
        assert result["evidence_text"] == packet.evidence_text(
            EvidenceSource.LOGS, result["ref"]
        )
    for result in traces:
        assert result["evidence_text"] == packet.evidence_text(
            EvidenceSource.TRACES, result["ref"]
        )


def test_search_logs_applies_filters():
    logs = search_logs(
        "inc-payment-001",
        service="payment",
        severity="error",
        query="INVALID TOKEN",
    )

    assert [entry["ref"] for entry in logs] == ["log:payment-001"]


def test_search_logs_rejects_unknown_severity():
    with pytest.raises(ValueError, match="Unsupported log severity"):
        search_logs("inc-payment-001", severity="fatal")


def test_unknown_incident_id_fails_explicitly():
    with pytest.raises(FileNotFoundError, match="No incident fixture found"):
        get_metrics("inc-does-not-exist")


def test_adversarial_fixture_has_no_metrics_or_traces():
    incident_id = "inc-adversarial-003"

    assert get_metrics(incident_id) == []
    assert get_traces(incident_id) == []
    assert any(
        "restart all services" in entry["message"]
        for entry in search_logs(incident_id)
    )