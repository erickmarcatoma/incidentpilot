"""SQLite persistence for remediation plans in the human approval queue."""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.schemas import PlanStatus, RemediationPlan


def database_path() -> Path:
    return Path(
        os.getenv(
            "INCIDENTPILOT_DB_PATH",
            str(Path(__file__).with_name("incidentpilot.sqlite3")),
        )
    )


def initialize_database(path: Path | None = None) -> None:
    resolved_path = path or database_path()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(resolved_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS approvals (
                plan_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                status TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def insert_plan(plan: RemediationPlan, path: Path | None = None) -> RemediationPlan:
    """Insert a new plan into the approval queue and assign its id and timestamp."""
    resolved_path = path or database_path()
    initialize_database(resolved_path)
    now = datetime.now(timezone.utc)
    saved = plan.model_copy(
        update={
            "plan_id": plan.plan_id or uuid.uuid4().hex,
            "created_at": plan.created_at or now,
        }
    )
    with sqlite3.connect(resolved_path) as connection:
        connection.execute(
            """
            INSERT INTO approvals (plan_id, incident_id, status, plan_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                saved.plan_id,
                saved.incident_id,
                saved.status.value,
                saved.model_dump_json(),
                saved.created_at.isoformat(),
            ),
        )
    return saved


def list_plans(path: Path | None = None) -> list[RemediationPlan]:
    resolved_path = path or database_path()
    initialize_database(resolved_path)
    with sqlite3.connect(resolved_path) as connection:
        rows = connection.execute(
            "SELECT plan_json FROM approvals ORDER BY created_at DESC, plan_id"
        ).fetchall()
    return [RemediationPlan.model_validate_json(row[0]) for row in rows]


def get_plan(plan_id: str, path: Path | None = None) -> RemediationPlan | None:
    resolved_path = path or database_path()
    initialize_database(resolved_path)
    with sqlite3.connect(resolved_path) as connection:
        row = connection.execute(
            "SELECT plan_json FROM approvals WHERE plan_id = ?", (plan_id,)
        ).fetchone()
    return RemediationPlan.model_validate_json(row[0]) if row else None


def update_plan_status(
    plan_id: str,
    status: PlanStatus,
    path: Path | None = None,
    reason: str | None = None,
) -> RemediationPlan | None:
    """Transition a pending plan exactly once; never run the plan."""
    resolved_path = path or database_path()
    initialize_database(resolved_path)
    with sqlite3.connect(resolved_path) as connection:
        row = connection.execute(
            "SELECT plan_json FROM approvals WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        if row is None:
            return None
        plan = RemediationPlan.model_validate_json(row[0])
        if plan.status is not PlanStatus.PENDING:
            return plan
        updated = plan.model_copy(
            update={
                "status": status,
                "reason": reason if reason is not None else plan.reason,
            }
        )
        cursor = connection.execute(
            """
            UPDATE approvals
            SET status = ?, plan_json = ?
            WHERE plan_id = ? AND status = ?
            """,
            (
                status.value,
                updated.model_dump_json(),
                plan_id,
                PlanStatus.PENDING.value,
            ),
        )
        if cursor.rowcount != 1:
            row = connection.execute(
                "SELECT plan_json FROM approvals WHERE plan_id = ?", (plan_id,)
            ).fetchone()
            return RemediationPlan.model_validate_json(row[0]) if row else None
    return updated

def supersede_pending(incident_id: str, path: Path | None = None) -> int:
    """Mark older pending plans for an incident as superseded (one active plan per incident)."""
    resolved_path = path or database_path()
    initialize_database(resolved_path)
    changed = 0
    with sqlite3.connect(resolved_path) as connection:
        rows = connection.execute(
            "SELECT plan_id, plan_json FROM approvals WHERE incident_id = ? AND status IN (?, ?)",
            (incident_id, PlanStatus.PENDING.value, PlanStatus.NEEDS_HUMAN.value),
        ).fetchall()
        for plan_id, plan_json in rows:
            plan = RemediationPlan.model_validate_json(plan_json)
            updated = plan.model_copy(update={"status": PlanStatus.SUPERSEDED})
            connection.execute(
                "UPDATE approvals SET status = ?, plan_json = ? WHERE plan_id = ?",
                (PlanStatus.SUPERSEDED.value, updated.model_dump_json(), plan_id),
            )
            changed += 1
    return changed
