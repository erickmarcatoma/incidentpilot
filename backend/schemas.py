"""Shared data contracts for IncidentPilot (PRD section 3e).

Both agents and the orchestrator import from here. Changing a field means
bumping SCHEMA_VERSION and telling the other person the same day.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"


class Strict(BaseModel):
    """Base model: unknown fields are rejected, so typos fail loudly."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Category(str, Enum):
    SERVICE_FAILURE = "service_failure"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    CONFIG_CHANGE = "config_change"
    NETWORK = "network"
    DEPENDENCY = "dependency"
    UNKNOWN = "unknown"


class DiagnosisStatus(str, Enum):
    """Set by the orchestrator, never by an LLM."""

    OK = "ok"
    UNCERTAIN = "uncertain"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    FAILED = "failed"


class EvidenceSource(str, Enum):
    METRICS = "metrics"
    LOGS = "logs"
    TRACES = "traces"


class PolicyResult(str, Enum):
    ALLOWED = "allowed"
    REQUIRES_APPROVAL = "requires_approval"
    REJECTED = "rejected"


class PlanStatus(str, Enum):
    """Where a plan is in the approval queue."""

    PENDING = "pending"
    NEEDS_HUMAN = "needs_human"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"  # a newer plan exists for the same incident
    STALE = "stale"  # the incident changed after the plan was made
    EXECUTED = "executed"
    RECOVERED = "recovered"
    NOT_RECOVERED = "not_recovered"


# ---------------------------------------------------------------------------
# Incident Packet: what the alert hands to Triage, and what tools return
# ---------------------------------------------------------------------------


class TimeWindow(Strict):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def start_before_end(self) -> TimeWindow:
        if self.start >= self.end:
            raise ValueError("window.start must be before window.end")
        return self

    def contains(self, other: TimeWindow) -> bool:
        return self.start <= other.start and other.end <= self.end


class Alert(Strict):
    name: str
    service: str
    fired_at: datetime
    description: str = ""


class MetricPoint(Strict):
    timestamp: datetime
    value: float


class MetricSeries(Strict):
    ref: str  # evidence reference id, e.g. "metric:checkout:error_rate"
    metric: str
    service: str
    baseline: float | None = None
    points: list[MetricPoint]


class LogEntry(Strict):
    ref: str  # evidence reference id, e.g. "log:000123"
    timestamp: datetime
    service: str
    severity: Literal["debug", "info", "warning", "error", "critical"]
    message: str


class Span(Strict):
    service: str
    operation: str
    duration_ms: float
    error: bool = False
    error_message: str | None = None


class Trace(Strict):
    ref: str  # evidence reference id, e.g. "trace:4bf92f35"
    trace_id: str
    spans: list[Span]


class IncidentPacket(Strict):
    """Everything known about one incident. Also the recorded fixture format."""

    schema_version: str = SCHEMA_VERSION
    incident_id: str
    alert: Alert
    window: TimeWindow
    services: list[str] = Field(min_length=1)
    metrics: list[MetricSeries] = []
    logs: list[LogEntry] = []
    traces: list[Trace] = []

    def evidence_text(self, source: EvidenceSource, ref: str) -> str | None:
        """Return the raw text behind an evidence ref, or None if it doesn't exist.

        The orchestrator uses this to check that every quote is real.
        """
        if source is EvidenceSource.LOGS:
            for entry in self.logs:
                if entry.ref == ref:
                    return entry.message
        elif source is EvidenceSource.METRICS:
            for series in self.metrics:
                if series.ref == ref:
                    values = " ".join(repr(p.value) for p in series.points)
                    return f"{series.metric} {series.service} baseline={series.baseline} {values}"
        elif source is EvidenceSource.TRACES:
            for trace in self.traces:
                if trace.ref == ref:
                    return " ".join(
                        f"{s.service} {s.operation} {s.duration_ms} {s.error_message or ''}"
                        for s in trace.spans
                    )
        return None


# ---------------------------------------------------------------------------
# Root-Cause Report: Triage -> orchestrator -> Remediation
# ---------------------------------------------------------------------------


class Evidence(Strict):
    source: EvidenceSource
    ref: str = Field(min_length=1)
    quote: str = Field(min_length=1)  # exactly as the tool returned it


class Hypothesis(Strict):
    id: str = Field(pattern=r"^H[1-3]$")
    cause: str = Field(min_length=1)
    category: Category
    service: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(min_length=1)


class TimelineEvent(Strict):
    time: datetime
    service: str
    event: str


class RootCauseReport(Strict):
    """What the Triage Agent returns. `status` is filled in by the orchestrator."""

    schema_version: str = SCHEMA_VERSION
    incident_id: str
    window: TimeWindow
    affected_services: list[str] = Field(min_length=1)
    timeline: list[TimelineEvent] = []
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=3)
    unknowns: list[str] = []
    status: DiagnosisStatus | None = None
    validation_notes: list[str] = []  # e.g. "H2 removed: evidence not found"
    created_at: datetime | None = None

    @field_validator("hypotheses")
    @classmethod
    def unique_and_ranked(cls, hypotheses: list[Hypothesis]) -> list[Hypothesis]:
        ids = [h.id for h in hypotheses]
        if len(ids) != len(set(ids)):
            raise ValueError("hypothesis ids must be unique")
        confidences = [h.confidence for h in hypotheses]
        if confidences != sorted(confidences, reverse=True):
            raise ValueError("hypotheses must be sorted by confidence, highest first")
        return hypotheses


# ---------------------------------------------------------------------------
# Remediation Plan: Remediation -> approval queue -> human -> executor
# ---------------------------------------------------------------------------


class PlanStep(Strict):
    action: str  # must match an action in allowed-actions.yaml
    target_service: str  # exactly one service per step
    policy_result: PolicyResult
    runbook_step: str = ""  # the runbook line this step comes from


class RecoveryCheck(Strict):
    metric: str
    service: str
    threshold: float
    within_minutes: int = Field(default=5, gt=0)


class RunbookRef(Strict):
    file: str
    section: str


class RemediationPlan(Strict):
    schema_version: str = SCHEMA_VERSION
    plan_id: str | None = None  # set by submit_remediation_plan
    incident_id: str
    addresses_hypothesis: str | None = Field(default=None, pattern=r"^H[1-3]$")
    alternative_hypothesis: str | None = Field(default=None, pattern=r"^H[1-3]$")
    runbook: RunbookRef | None = None
    steps: list[PlanStep] = []
    risk: str = ""
    rollback: str = ""
    recovery_check: RecoveryCheck | None = None
    incident_summary: str = Field(min_length=1)
    diagnosis_status: DiagnosisStatus  # carried over from the report
    status: PlanStatus = PlanStatus.PENDING
    reason: str = ""  # one line when status is needs_human
    based_on_report_at: datetime | None = None  # used by the stale-plan check
    created_at: datetime | None = None

    @model_validator(mode="after")
    def consistent(self) -> RemediationPlan:
        if any(step.policy_result is PolicyResult.REJECTED for step in self.steps):
            raise ValueError("a plan must not contain a step that policy rejected")
        if self.status is PlanStatus.NEEDS_HUMAN:
            if self.steps:
                raise ValueError("a needs_human plan must have no steps")
            if not self.reason:
                raise ValueError("a needs_human plan must give a one-line reason")
        elif self.status is PlanStatus.PENDING:
            if not self.steps:
                raise ValueError("a pending plan needs at least one step (or use needs_human)")
            if self.addresses_hypothesis is None:
                raise ValueError("a pending plan must name the hypothesis it addresses")
            if self.runbook is None or self.recovery_check is None:
                raise ValueError("a pending plan needs a runbook and a recovery check")
            if not self.rollback:
                raise ValueError("a pending plan needs rollback steps")
        if self.diagnosis_status in (DiagnosisStatus.INSUFFICIENT_EVIDENCE, DiagnosisStatus.FAILED):
            if self.status is PlanStatus.PENDING:
                raise ValueError("a plan built on an insufficient or failed diagnosis must be needs_human")
        return self