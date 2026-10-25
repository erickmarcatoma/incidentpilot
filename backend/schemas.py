"""Shared data contracts for IncidentPilot (PRD section 3e)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Category(str, Enum):
    SERVICE_FAILURE = "service_failure"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    CONFIG_CHANGE = "config_change"
    NETWORK = "network"
    DEPENDENCY = "dependency"
    UNKNOWN = "unknown"


class DiagnosisStatus(str, Enum):
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
    PENDING = "pending"
    NEEDS_HUMAN = "needs_human"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    STALE = "stale"
    EXECUTED = "executed"
    RECOVERED = "recovered"
    NOT_RECOVERED = "not_recovered"


class TimeWindow(Strict):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def start_before_end(self) -> "TimeWindow":
        if self.start >= self.end:
            raise ValueError("window.start must be before window.end")
        return self

    def contains(self, other: "TimeWindow") -> bool:
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
    ref: str
    metric: str
    service: str
    baseline: Optional[float] = None
    points: list[MetricPoint] = []


class LogEntry(Strict):
    ref: str
    timestamp: datetime
    service: str
    severity: Literal["debug", "info", "warning", "error", "critical"]
    message: str


class Span(Strict):
    service: str
    operation: str
    duration_ms: float
    error: bool = False
    error_message: Optional[str] = None


class Trace(Strict):
    ref: str
    trace_id: str
    spans: list[Span] = []


class IncidentPacket(Strict):
    schema_version: str = SCHEMA_VERSION
    incident_id: str
    alert: Alert
    window: TimeWindow
    services: list[str] = Field(min_length=1)
    metrics: list[MetricSeries] = []
    logs: list[LogEntry] = []
    traces: list[Trace] = []

    def evidence_text(self, source: EvidenceSource, ref: str) -> Optional[str]:
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


class Evidence(Strict):
    source: EvidenceSource
    ref: str = Field(min_length=1)
    quote: str = Field(min_length=1)


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
    schema_version: str = SCHEMA_VERSION
    incident_id: str
    window: TimeWindow
    affected_services: list[str] = Field(min_length=1)
    timeline: list[TimelineEvent] = []
    hypotheses: list[Hypothesis] = Field(max_length=3)
    unknowns: list[str] = []
    status: Optional[DiagnosisStatus] = None
    validation_notes: list[str] = []
    created_at: Optional[datetime] = None

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

    @model_validator(mode="after")
    def require_hypothesis_unless_insufficient(self) -> "RootCauseReport":
        if not self.hypotheses and self.status is not DiagnosisStatus.INSUFFICIENT_EVIDENCE:
            raise ValueError("a report without hypotheses must be insufficient_evidence")
        return self


class PlanStep(Strict):
    action: str
    target_service: str
    policy_result: PolicyResult
    runbook_step: str = ""


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
    plan_id: Optional[str] = None
    incident_id: str
    addresses_hypothesis: Optional[str] = Field(default=None, pattern=r"^H[1-3]$")
    alternative_hypothesis: Optional[str] = Field(default=None, pattern=r"^H[1-3]$")
    runbook: Optional[RunbookRef] = None
    steps: list[PlanStep] = []
    risk: str = ""
    rollback: str = ""
    recovery_check: Optional[RecoveryCheck] = None
    incident_summary: str = Field(min_length=1)
    diagnosis_status: DiagnosisStatus
    status: PlanStatus = PlanStatus.PENDING
    reason: str = ""
    based_on_report_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    @model_validator(mode="after")
    def consistent(self) -> "RemediationPlan":
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
        if self.diagnosis_status in (
            DiagnosisStatus.INSUFFICIENT_EVIDENCE,
            DiagnosisStatus.FAILED,
        ):
            if self.status is PlanStatus.PENDING:
                raise ValueError(
                    "a plan built on an insufficient or failed diagnosis must be needs_human"
                )
        return self


__all__ = [
    "Alert",
    "Category",
    "DiagnosisStatus",
    "Evidence",
    "EvidenceSource",
    "Hypothesis",
    "IncidentPacket",
    "LogEntry",
    "MetricPoint",
    "MetricSeries",
    "PlanStatus",
    "PlanStep",
    "PolicyResult",
    "RecoveryCheck",
    "RootCauseReport",
    "RunbookRef",
    "Span",
    "Strict",
    "TimeWindow",
    "Trace",
    "RemediationPlan",
]