"""Rule-based remediation planner (baseline).

Turns the filtered handoff (`RemediationInput`) into a `RemediationPlan` using
Kamal's `find_runbook` and `check_policy`. No LLM is involved, so nothing in
untrusted telemetry can steer it. Rules follow docs/PLAN_SAFETY_RULES.md:

- Steps come only from the matched runbook's Remediation Steps.
- Every step passes `check_policy`; the plan uses the first allowed step that
  targets the hypothesis's service (smallest change that addresses it).
- `needs_human` with no steps when the diagnosis is insufficient or failed,
  telemetry is incomplete, no runbook matches, or policy allows no step.
- Uncertain diagnoses name H2 as the alternative.

The LLM Remediation Agent can replace this function later; main.py picks one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from backend.agents.remediation.tools import check_policy, find_runbook
from backend.handoff import RemediationInput
from backend.schemas import (
    DiagnosisStatus,
    IncidentPacket,
    PlanStatus,
    PlanStep,
    PolicyResult,
    RecoveryCheck,
    RemediationPlan,
    RunbookRef,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_MARGIN = 1.25  # "back to baseline" means within 25% of the pre-incident value

RISK_BY_ACTION = {
    "toggle_feature_flag": "Low. A reversible flag change on one service.",
    "restart_service": "Medium. Brief interruption for one service; relief may be temporary if the cause remains.",
    "scale_service": "Medium. Changes capacity for one service; reversible.",
    "rollback_deployment": "Medium. Reverts one service to its previous release.",
    "clear_cache": "Low. Clears one service's cache; it refills on demand.",
}


@dataclass(frozen=True)
class RunbookStep:
    title: str
    action: str
    target_service: str


@dataclass(frozen=True)
class ParsedRunbook:
    path: Path
    steps: list[RunbookStep]
    rollback: str
    recovery_metric: str | None
    recovery_service: str | None
    recovery_threshold: float | None
    recovery_minutes: int


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(1) if match else ""


def parse_runbook(path: Path) -> ParsedRunbook:
    text = path.read_text(encoding="utf-8")

    steps = []
    for block in re.split(r"^### ", _section(text, "Remediation Steps"), flags=re.M)[1:]:
        title = block.splitlines()[0].strip()
        title = re.sub(r"^Step \d+:\s*", "", title)
        action = re.search(r"\*\*Action:\*\*\s*([a-z_]+)", block)
        target = re.search(r"\*\*Target Service:\*\*\s*([a-z][a-z0-9-]*)", block)
        if action and target:
            steps.append(RunbookStep(title, action.group(1), target.group(1)))

    rollback_lines = [
        line.strip()[2:].strip()
        for line in _section(text, "Rollback Steps").splitlines()
        if line.strip().startswith("- ")
    ]

    recovery = _section(text, "Recovery Check")
    metric_line = re.search(r"\*\*Metric:\*\*\s*(.+)", recovery)
    metric = service = None
    if metric_line:
        on_service = re.search(r"([a-z_]+)\s+on service\s+([a-z][a-z0-9-]*)", metric_line.group(1))
        if on_service:
            metric, service = on_service.group(1), on_service.group(2)
    threshold_line = re.search(r"\*\*Threshold:\*\*\s*(.+)", recovery)
    # Only a number after below/above/under/over is a threshold ("within 10 minutes" is a time, not a level).
    number = (
        re.search(r"(?:below|above|under|over)\s+(\d+(?:\.\d+)?)", threshold_line.group(1))
        if threshold_line
        else None
    )
    minutes = re.search(r"within (\d+) minutes?", recovery)

    return ParsedRunbook(
        path=path,
        steps=steps,
        rollback="; ".join(rollback_lines),
        recovery_metric=metric,
        recovery_service=service,
        recovery_threshold=float(number.group(1)) if number else None,
        recovery_minutes=int(minutes.group(1)) if minutes else 5,
    )


def _baseline(packet: IncidentPacket | None, metric: str, service: str) -> float | None:
    if packet is None:
        return None
    for series in packet.metrics:
        if series.metric == metric and series.service == service and series.baseline is not None:
            return series.baseline
    return None


def _needs_human(handoff: RemediationInput, reason: str) -> RemediationPlan:
    return RemediationPlan(
        incident_id=handoff.incident_id,
        steps=[],
        incident_summary=f"{reason} No automated step was proposed. A person should review the incident.",
        diagnosis_status=handoff.diagnosis_status,
        status=PlanStatus.NEEDS_HUMAN,
        reason=reason,
        based_on_report_at=handoff.report_created_at,
    )


def plan_remediation(handoff: RemediationInput, packet: IncidentPacket | None = None) -> RemediationPlan | None:
    """Build a plan from the filtered handoff. Returns None for a failed diagnosis (PRD 3e)."""
    if handoff.diagnosis_status is DiagnosisStatus.FAILED:
        return None
    if handoff.diagnosis_status is DiagnosisStatus.INSUFFICIENT_EVIDENCE or not handoff.hypotheses:
        return _needs_human(handoff, "Insufficient evidence for a diagnosis.")
    if not handoff.telemetry_complete:
        return _needs_human(handoff, "Diagnosis incomplete: some telemetry was unavailable.")

    h1 = handoff.hypotheses[0]
    if not handoff.h1_evidence_matches_service:
        # Red-team finding C1: never act on a service the evidence doesn't implicate.
        return _needs_human(handoff, f"{h1.id} blames {h1.service}, but none of its evidence comes from {h1.service}.")
    ref = find_runbook(h1.category.value, h1.service)
    if ref is None:
        return _needs_human(handoff, f"No runbook matches {h1.category.value} in {h1.service}.")

    runbook = parse_runbook(Path(ref.file))
    chosen: tuple[RunbookStep, PolicyResult] | None = None
    for step in runbook.steps:
        if step.target_service != h1.service:
            continue  # one service only: the one H1 blames
        result = check_policy(step.action, step.target_service)
        if result is not PolicyResult.REJECTED:
            chosen = (step, result)
            break
    if chosen is None:
        return _needs_human(handoff, f"Policy allows no runbook step for {h1.service}.")
    step, policy = chosen

    if runbook.recovery_metric and runbook.recovery_service:
        threshold = runbook.recovery_threshold
        if threshold is None:  # e.g. "return to baseline"
            baseline = _baseline(packet, runbook.recovery_metric, runbook.recovery_service)
            threshold = round(baseline * BASELINE_MARGIN, 2) if baseline is not None else None
        recovery = (
            RecoveryCheck(
                metric=runbook.recovery_metric,
                service=runbook.recovery_service,
                threshold=threshold,
                within_minutes=runbook.recovery_minutes,
            )
            if threshold is not None
            else None
        )
    else:
        recovery = None
    if recovery is None or not runbook.rollback:
        return _needs_human(handoff, f"The runbook for {h1.service} has no usable rollback or recovery check.")

    alternative = None
    if handoff.diagnosis_status is DiagnosisStatus.UNCERTAIN and len(handoff.hypotheses) > 1:
        alternative = handoff.hypotheses[1].id

    status_word = {DiagnosisStatus.OK: "Confident", DiagnosisStatus.UNCERTAIN: "Uncertain"}[handoff.diagnosis_status]
    summary = (
        f"{status_word} diagnosis: {h1.id} is {h1.category.value.replace('_', ' ')} in {h1.service} "
        f"(confidence {h1.confidence:.2f}). Plan: {step.action.replace('_', ' ')} on {h1.service}, "
        f"from the {runbook.path.stem.replace('-', ' ')} runbook."
    )
    if alternative:
        summary += f" Alternative to check if this does not recover: {alternative}."

    return RemediationPlan(
        incident_id=handoff.incident_id,
        addresses_hypothesis=h1.id,
        alternative_hypothesis=alternative,
        runbook=RunbookRef(file=str(runbook.path.relative_to(REPO_ROOT)), section=step.title),
        steps=[PlanStep(action=step.action, target_service=h1.service, policy_result=policy, runbook_step=step.title)],
        risk=RISK_BY_ACTION.get(step.action, "Unknown. Review before approving."),
        rollback=runbook.rollback,
        recovery_check=recovery,
        incident_summary=summary,
        diagnosis_status=handoff.diagnosis_status,
        status=PlanStatus.PENDING,
        based_on_report_at=handoff.report_created_at,
    )


__all__ = ["parse_runbook", "plan_remediation"]
