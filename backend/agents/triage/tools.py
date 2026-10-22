"""Read-only investigation tools backed by recorded incident fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from backend.schemas import EvidenceSource, IncidentPacket, MetricSeries, Trace

_FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures"
_LOG_SEVERITIES = {"debug", "info", "warning", "error", "critical"}


def load_incident_packet(incident_id: str) -> IncidentPacket:
    """Load a fixture by its incident id; unknown ids fail explicitly."""
    for fixture_path in sorted(_FIXTURES_DIR.glob("*.json")):
        if fixture_path.name == "sample_report_case1.json":
            continue
        with fixture_path.open(encoding="utf-8") as fixture_file:
            data = json.load(fixture_file)
        if data.get("incident_id") == incident_id:
            return IncidentPacket.model_validate(data)
    raise FileNotFoundError(f"No incident fixture found for {incident_id!r}")


def get_metrics(incident_id: str) -> list[dict[str, object]]:
    """Return the metric series recorded for an incident."""
    packet = load_incident_packet(incident_id)
    return [
        _metric_result(series, packet.evidence_text(EvidenceSource.METRICS, series.ref))
        for series in packet.metrics
    ]


def search_logs(
    incident_id: str,
    service: str | None = None,
    severity: str | None = None,
    query: str | None = None,
) -> list[dict[str, object]]:
    """Search recorded logs by exact service/severity and a case-insensitive substring."""
    if severity is not None and severity not in _LOG_SEVERITIES:
        raise ValueError(f"Unsupported log severity: {severity!r}")

    packet = load_incident_packet(incident_id)
    query_text = query.casefold() if query is not None else None
    return [
        {
            **entry.model_dump(mode="json"),
            "evidence_text": entry.message,
        }
        for entry in packet.logs
        if (service is None or entry.service == service)
        and (severity is None or entry.severity == severity)
        and (query_text is None or query_text in entry.message.casefold())
    ]


def get_traces(incident_id: str) -> list[dict[str, object]]:
    """Return the traces recorded for an incident."""
    packet = load_incident_packet(incident_id)
    return [
        _trace_result(trace, packet.evidence_text(EvidenceSource.TRACES, trace.ref))
        for trace in packet.traces
    ]


def _metric_result(series: MetricSeries, evidence_text: str | None) -> dict[str, object]:
    return {
        **series.model_dump(mode="json"),
        "evidence_text": evidence_text,
    }


def _trace_result(trace: Trace, evidence_text: str | None) -> dict[str, object]:
    return {
        **trace.model_dump(mode="json"),
        "evidence_text": evidence_text,
    }