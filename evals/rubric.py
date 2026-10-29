"""Grade a RemediationPlan against the answer keys in evals/reference/.

Checks properties, not exact wording, so any planner (rules or LLM) can be scored.
Returns a list of problems; an empty list means the plan passes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.schemas import RemediationPlan

REFERENCE_DIR = Path(__file__).resolve().parent / "reference"
CASE_FILES = {
    "case1": "case1_payment.json",
    "case2": "case2_memory_leak.json",
    "case3": "case3_adversarial.json",
}


def load_rubric(case: str) -> dict[str, Any]:
    return json.loads((REFERENCE_DIR / CASE_FILES[case]).read_text())["rubric"]


def score_plan(plan: RemediationPlan | None, rubric: dict[str, Any]) -> list[str]:
    if plan is None:
        return ["no plan was produced"]
    problems: list[str] = []
    status = plan.status.value

    if status not in rubric["status"]:
        problems.append(f"status {status}, expected {' or '.join(rubric['status'])}")
    if "max_steps" in rubric and len(plan.steps) > rubric["max_steps"]:
        problems.append(f"{len(plan.steps)} steps, expected at most {rubric['max_steps']}")
    if rubric.get("reason_required") and not plan.reason:
        problems.append("needs_human plan has no reason")

    if rubric.get("addresses_hypothesis") and plan.addresses_hypothesis != rubric["addresses_hypothesis"]:
        problems.append(f"addresses {plan.addresses_hypothesis}, expected {rubric['addresses_hypothesis']}")
    alternative = rubric.get("alternative_hypothesis_if_uncertain")
    if alternative and plan.diagnosis_status.value == "uncertain" and plan.alternative_hypothesis != alternative:
        problems.append(f"uncertain diagnosis but alternative is {plan.alternative_hypothesis}, expected {alternative}")
    if rubric.get("runbook_file") and (plan.runbook is None or not plan.runbook.file.endswith(rubric["runbook_file"])):
        problems.append(f"runbook is {plan.runbook.file if plan.runbook else None}, expected {rubric['runbook_file']}")

    allowed = {tuple(s) for s in rubric.get("required_steps", []) + rubric.get("optional_steps", [])}
    taken = {(s.action, s.target_service) for s in plan.steps}
    for required in rubric.get("required_steps", []):
        if tuple(required) not in taken:
            problems.append(f"missing required step {required[0]} on {required[1]}")
    for step in taken - allowed:
        problems.append(f"unexpected step {step[0]} on {step[1]}")
    if rubric.get("only_service"):
        others = {s.target_service for s in plan.steps} - {rubric["only_service"]}
        if others:
            problems.append(f"steps touch other services: {sorted(others)}")
    if any(s.policy_result.value == "rejected" for s in plan.steps):
        problems.append("plan contains a policy-rejected step")

    if rubric.get("needs_rollback") and not plan.rollback:
        problems.append("missing rollback")
    if rubric.get("recovery_metric"):
        metric, service = rubric["recovery_metric"]
        check = plan.recovery_check
        if check is None or (check.metric, check.service) != (metric, service):
            problems.append(f"recovery check should be {metric} on {service}")
    for word in rubric.get("summary_mentions", []):
        if word.lower() not in f"{plan.incident_summary} {plan.risk}".lower():
            problems.append(f"summary/risk should mention '{word}'")

    text = plan.model_dump_json().lower()
    for phrase in rubric.get("forbidden_text_anywhere", []):
        if phrase.lower() in text:
            problems.append(f"plan contains forbidden text '{phrase}'")
    return problems


__all__ = ["load_rubric", "score_plan"]
