"""The Triage -> Remediation handoff (PRD 3e, docs/PLAN_SAFETY_RULES.md section 3).

The Remediation side receives only structured fields from a validated report.
Free text (cause, evidence quotes, timeline, unknowns, validation notes) never
crosses this boundary, because it can carry text from untrusted telemetry.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.schemas import Category, DiagnosisStatus, IncidentPacket, RootCauseReport

# Text that must never reach the Remediation side. The canary is planted in case 3's fixture.
CANARY = "CANARY-7f3a9c"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HandoffHypothesis(_Strict):
    id: str = Field(pattern=r"^H[1-3]$")
    category: Category
    service: str = Field(pattern=r"^[a-z][a-z0-9-]{0,40}$")
    confidence: float = Field(ge=0.0, le=1.0)


class RemediationInput(_Strict):
    """Everything the Remediation Agent may know about an incident. Nothing else."""

    incident_id: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    diagnosis_status: DiagnosisStatus
    telemetry_complete: bool  # set by code from the packet, never from text
    hypotheses: list[HandoffHypothesis] = Field(max_length=3)
    report_created_at: datetime | None = None

    @field_validator("hypotheses")
    @classmethod
    def ranked(cls, hypotheses: list[HandoffHypothesis]) -> list[HandoffHypothesis]:
        confidences = [h.confidence for h in hypotheses]
        if confidences != sorted(confidences, reverse=True):
            raise ValueError("hypotheses must be sorted by confidence")
        return hypotheses


ALLOWED_FIELDS = frozenset(RemediationInput.model_fields)
ALLOWED_HYPOTHESIS_FIELDS = frozenset(HandoffHypothesis.model_fields)


class HandoffError(ValueError):
    """The report cannot be handed to Remediation."""


def build_remediation_input(packet: IncidentPacket, report: RootCauseReport) -> RemediationInput:
    """Copy only structured fields from a validated report. Never copies free text."""
    if report.status is None:
        raise HandoffError("report has not been validated by the orchestrator")
    if report.incident_id != packet.incident_id:
        raise HandoffError("report does not belong to this incident")
    unknown = [h.service for h in report.hypotheses if h.service not in packet.services]
    if unknown:
        raise HandoffError(f"hypothesis service not in the incident packet: {unknown}")

    return RemediationInput(
        incident_id=report.incident_id,
        diagnosis_status=report.status,
        telemetry_complete=bool(packet.metrics and packet.logs and packet.traces),
        hypotheses=[
            HandoffHypothesis(id=h.id, category=h.category, service=h.service, confidence=h.confidence)
            for h in report.hypotheses
        ],
        report_created_at=report.created_at,
    )


def payload_leaks(payload_json: str, forbidden: list[str]) -> list[str]:
    """Return every forbidden string found anywhere in the serialized payload."""
    lowered = payload_json.lower()
    return [text for text in forbidden if text.lower() in lowered]


__all__ = [
    "ALLOWED_FIELDS",
    "ALLOWED_HYPOTHESIS_FIELDS",
    "CANARY",
    "HandoffError",
    "RemediationInput",
    "build_remediation_input",
    "payload_leaks",
]
