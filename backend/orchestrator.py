"""IncidentPilot orchestrator: validates Triage reports before Remediation."""

from __future__ import annotations

from backend.schemas import DiagnosisStatus, IncidentPacket, RootCauseReport


def validate_report(
    packet: IncidentPacket,
    report: RootCauseReport | dict,
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
        valid_hypotheses.append(hypothesis)

    if not valid_hypotheses:
        status = DiagnosisStatus.INSUFFICIENT_EVIDENCE
    elif len(valid_hypotheses) > 1:
        status = DiagnosisStatus.UNCERTAIN
    else:
        status = DiagnosisStatus.OK

    return validated.model_copy(
        update={
            "hypotheses": valid_hypotheses,
            "status": status,
            "validation_notes": notes,
        }
    )


__all__ = ["validate_report"]