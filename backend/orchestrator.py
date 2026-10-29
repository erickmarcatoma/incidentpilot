from __future__ import annotations

from backend.schemas import (
    DiagnosisStatus,
    IncidentPacket,
    RootCauseReport,
)

# PRD 3e thresholds (starting values, tune on the test scenarios)
MIN_TOP_CONFIDENCE = 0.5
MIN_CONFIDENCE_GAP = 0.15

# A quote must be specific enough to point at one record (red-team finding A1:
# a one-letter quote like "a" used to pass as "verified" evidence).
MIN_QUOTE_CHARS = 12
MIN_QUOTE_WORDS = 2
MIN_METRIC_VALUE_CHARS = 3  # a metric quote may be a single value, e.g. "0.9103"


def _quote_problem(packet: IncidentPacket, evidence) -> str | None:
    """Return why a piece of evidence can't be trusted, or None if it is fine."""
    source_text = packet.evidence_text(evidence.source, evidence.ref)
    if source_text is None:
        return "reference not found"
    quote = evidence.quote.strip()
    if quote not in source_text:
        return "quote not found"
    if evidence.source.value == "metrics":
        try:
            value = float(quote)
        except ValueError:
            value = None
        if value is not None:
            values = {
                point.value
                for series in packet.metrics
                if series.ref == evidence.ref
                for point in series.points
            }
            if len(quote) >= MIN_METRIC_VALUE_CHARS and value in values:
                return None
            return "metric value not in that series"
    if len(quote) < MIN_QUOTE_CHARS or len(quote.split()) < MIN_QUOTE_WORDS:
        return f"quote too short to be evidence ({len(quote)} chars)"
    return None


def validate_report(
    packet: IncidentPacket,
    report: RootCauseReport | dict[str, object],
) -> RootCauseReport:
    """Validate a triage report against its incident and the packet's evidence."""
    validated = RootCauseReport.model_validate(report)
    notes = list(validated.validation_notes)

    consistency_errors: list[str] = []
    if validated.incident_id != packet.incident_id:
        consistency_errors.append("incident_id does not match the incident packet")
    if validated.window != packet.window:
        consistency_errors.append("report window does not match the incident packet")
    if not set(validated.affected_services).issubset(packet.services):
        consistency_errors.append(
            "affected_services contains a service outside the incident packet"
        )
    if any(event.service not in packet.services for event in validated.timeline):
        consistency_errors.append("timeline contains a service outside the incident packet")
    if any(
        not packet.window.start <= event.time <= packet.window.end
        for event in validated.timeline
    ):
        consistency_errors.append("timeline contains an event outside the incident window")

    if consistency_errors:
        notes.extend(consistency_errors)
        return validated.model_copy(
            update={"status": DiagnosisStatus.FAILED, "validation_notes": notes}
        )

    valid_hypotheses = []
    for hypothesis in validated.hypotheses:
        if hypothesis.service not in validated.affected_services:
            notes.append(
                f"{hypothesis.id} removed: service is not listed as affected"
            )
            continue

        problems = [
            problem
            for evidence in hypothesis.evidence
            if (problem := _quote_problem(packet, evidence)) is not None
        ]
        if problems:
            notes.append(
                f"{hypothesis.id} removed: evidence reference or quote not found ({problems[0]})"
            )
            continue
        valid_hypotheses.append(hypothesis)

    if not valid_hypotheses:
        status = DiagnosisStatus.INSUFFICIENT_EVIDENCE
    else:
        top = valid_hypotheses[0].confidence
        second = valid_hypotheses[1].confidence if len(valid_hypotheses) > 1 else None
        if top < MIN_TOP_CONFIDENCE or (
            second is not None and top - second <= MIN_CONFIDENCE_GAP
        ):
            status = DiagnosisStatus.UNCERTAIN
        else:
            status = DiagnosisStatus.OK

    if valid_hypotheses:
        top = valid_hypotheses[0]
        evidence_services = set().union(
            *(packet.evidence_services(e.source, e.ref) for e in top.evidence)
        )
        if top.service not in evidence_services:
            notes.append(
                f"{top.id} blames {top.service}, but none of its evidence comes from {top.service}"
            )
            if status is DiagnosisStatus.OK:
                status = DiagnosisStatus.UNCERTAIN

    missing = [
        name
        for name, data in (
            ("metrics", packet.metrics),
            ("logs", packet.logs),
            ("traces", packet.traces),
        )
        if not data
    ]
    if missing:
        notes.append(f"Diagnosis incomplete: {', '.join(missing)} unavailable")
        if status is DiagnosisStatus.OK:
            status = DiagnosisStatus.UNCERTAIN

    return validated.model_copy(
        update={
            "hypotheses": valid_hypotheses,
            "status": status,
            "validation_notes": notes,
        }
    )


__all__ = ["validate_report"]