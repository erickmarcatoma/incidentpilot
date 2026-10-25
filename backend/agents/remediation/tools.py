"""Remediation tools: find_runbook, check_policy, submit_remediation_plan."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import yaml

from backend.schemas import PolicyResult, RunbookRef

_RUNBOOKS_DIR = Path(__file__).resolve().parents[2] / "knowledge" / "runbooks"
_POLICIES_FILE = Path(__file__).resolve().parents[2] / "knowledge" / "policies" / "allowed-actions.yaml"
_DB_PATH = Path(__file__).resolve().parents[3] / "approvals.db"


def find_runbook(category: str, service: str) -> RunbookRef | None:
    """Find the runbook section that matches a root-cause category and service.

    Args:
        category: One of service_failure, resource_exhaustion, config_change, network, dependency, unknown
        service: The service to find a runbook for

    Returns:
        RunbookRef with file path and section title, or None if no match
    """
    # Map category to runbook file
    category_to_file = {
        "service_failure": "payment-service-failure.md",
        "resource_exhaustion": "memory-leak.md",
        "config_change": "config-change.md",
        "network": "network-issue.md",
        "dependency": "dependency-failure.md",
    }

    filename = category_to_file.get(category)
    if not filename:
        return None

    runbook_path = _RUNBOOKS_DIR / filename
    if not runbook_path.exists():
        return None

    with runbook_path.open(encoding="utf-8") as f:
        content = f.read()

    # Check if the runbook is for the correct service
    if service not in content.lower():
        return None

    # Find the section title (first heading after the initial metadata)
    lines = content.split("\n")
    section_title = None
    for line in lines[1:]:  # Skip the first line with title
        if line.startswith("## "):
            section_title = line[3:].strip()
            break

    return RunbookRef(file=str(runbook_path), section=section_title or filename)


def check_policy(action: str, target_service: str) -> PolicyResult:
    """Check whether a proposed action is allowed and whether it needs approval.

    Args:
        action: The action to check (e.g., toggle_feature_flag, restart_service)
        target_service: The service the action would affect

    Returns:
        PolicyResult.ALLOWED, REQUIREMENTS_APPROVAL, or REJECTED
    """
    with _POLICIES_FILE.open(encoding="utf-8") as f:
        policy = yaml.safe_load(f)

    if not policy or "actions" not in policy:
        return PolicyResult.REJECTED

    for act in policy["actions"]:
        if act["action"] == action:
            # Check max scope
            if act.get("max_scope") == "multiple_services":
                return PolicyResult.REJECTED
            return PolicyResult.REQUIRES_APPROVAL if act.get("requires_approval") else PolicyResult.ALLOWED

    return PolicyResult.REJECTED


def submit_remediation_plan(plan_id: str, incident_id: str, plan_data: dict) -> dict:
    """Submit a remediation plan to the approval queue.

    This is the only write tool and cannot run any action directly.

    Args:
        plan_id: Unique identifier for the plan
        incident_id: The incident this plan addresses
        plan_data: The remediation plan as a dict

    Returns:
        Dict with submission result
    """
    conn = sqlite3.connect(_DB_PATH)
    cursor = conn.cursor()

    # Create table if not exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS approvals (
            plan_id TEXT PRIMARY KEY,
            incident_id TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute(
        "INSERT INTO approvals (plan_id, incident_id, plan_json) VALUES (?, ?, ?)",
        (plan_id, incident_id, json.dumps(plan_data)),
    )
    conn.commit()
    conn.close()

    return {"status": "submitted", "plan_id": plan_id, "queue_status": "pending"}


__all__ = ["find_runbook", "check_policy", "submit_remediation_plan"]