"""Executor: runs allow-listed actions after human approval."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.schemas import PlanStatus, RecoveryCheck, RemediationPlan

# Allow-list of actions the executor can run
ALLOWED_ACTIONS = {
    "restart_service": "Restarts a single service (graceful)",
    "toggle_feature_flag": "Enables or disables a feature flag on a service",
}

# Simulated service statuses for the demo
_SERVICE_HEALTH: dict[str, dict[str, float]] = {}


def check_policy(action: str, target_service: str) -> str:
    """Check if an action is allowed in the executor.

    Returns 'allowed', 'requires_approval', or 'rejected'.
    """
    if action not in ALLOWED_ACTIONS:
        return "rejected"
    return "allowed"


def execute_plan(plan: RemediationPlan) -> dict[str, Any]:
    """Execute a remediation plan step by step.

    Only allow-listed actions on one service at a time are executed.
    Each plan must already be approved.
    """
    from backend.db import get_connection

    conn = get_connection()
    row = conn.execute(
        "SELECT plan_json FROM approvals WHERE plan_id = ?",
        (plan.plan_id,),
    ).fetchone()
    conn.close()

    if not row:
        raise ValueError(f"Plan {plan.plan_id} not found in approval queue")

    stored_plan = RemediationPlan.model_validate_json(row["plan_json"])
    if stored_plan.status != PlanStatus.APPROVED:
        raise ValueError(f"Plan {plan.plan_id} must be approved before execution")

    results = []
    for step in plan.steps:
        if step.target_service != plan.steps[0].target_service:
            raise ValueError("Executor only supports one service per plan")

        action = step.action
        service = step.target_service

        if action not in ALLOWED_ACTIONS:
            results.append({"action": action, "target_service": service, "status": "rejected"})
            continue

        result = _run_action(action, service)
        results.append(result)

    # Mark plan as executed
    conn = get_connection()
    conn.execute(
        "UPDATE approvals SET status = ? WHERE plan_id = ?",
        (PlanStatus.EXECUTED.value, plan.plan_id),
    )
    conn.commit()
    conn.close()

    return {"plan_id": plan.plan_id, "results": results}


def _run_action(action: str, service: str) -> dict[str, Any]:
    """Actually run an action (simulated for the demo)."""
    if action == "restart_service":
        _SERVICE_HEALTH[service] = {
            "restarted_at": datetime.utcnow().isoformat(),
            "status": "healthy",
        }
        return {
            "action": action,
            "target_service": service,
            "status": "success",
            "message": f"Service {service} restarted",
        }
    elif action == "toggle_feature_flag":
        _SERVICE_HEALTH[service] = {
            "flag_changed_at": datetime.utcnow().isoformat(),
            "status": "healthy",
        }
        return {
            "action": action,
            "target_service": service,
            "status": "success",
            "message": f"Feature flag toggled on {service}",
        }
    return {"action": action, "target_service": service, "status": "rejected"}


def recovery_check(plan: RemediationPlan, recovery_check: RecoveryCheck) -> bool:
    """Check if the service has recovered after an action.

    Returns True if the metric is below threshold, False otherwise.
    """
    health = _SERVICE_HEALTH.get(recovery_check.service, {})
    if not health or health.get("status") != "healthy":
        return False
    return True


def is_plan_stale(plan: RemediationPlan, current_packet_data: dict) -> bool:
    """Check if a plan is stale (incident changed since plan was made)."""
    return False  # Simplified for now


__all__ = ["execute_plan", "recovery_check", "check_policy", "ALLOWED_ACTIONS", "is_plan_stale"]