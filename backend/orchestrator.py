from __future__ import annotations

from backend.schemas import (
    DiagnosisStatus,
    IncidentPacket,
    RootCauseReport,
)

# PRD 3e thresholds (starting values, tune on the test scenarios)
MIN_TOP_CONFIDENCE = 0.5
MIN_CONFIDENCE_GAP = 0.15


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

        invalid_evidence = [
            evidence
            for evidence in hypothesis.evidence
            if (
                (source_text := packet.evidence_text(evidence.source, evidence.ref))
                is None
                or evidence.quote not in source_text
            )
        ]
        if invalid_evidence:
            notes.append(
                f"{hypothesis.id} removed: evidence reference or quote not found"
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

    missing = [
        name
        for name, data in (
            ("metrics", packet.metrics),
            ("logs", packet.logs),
            ("traces", packet.traces),
        )
        if not data
    ]
    if missing and status is DiagnosisStatus.OK:
        status = DiagnosisStatus.UNCERTAIN
        notes.append(f"Diagnosis incomplete: {', '.join(missing)} unavailable")

    return validated.model_copy(
        update={
            "hypotheses": valid_hypotheses,
            "status": status,
            "validation_notes": notes,
        }
    )


__all__ = ["validate_report"]