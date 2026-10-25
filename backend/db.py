"""SQLite database for approval queue."""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "approvals.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create approvals table if it doesn't exist."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS approvals (
            plan_id TEXT PRIMARY KEY,
            incident_id TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def submit_plan(plan_id: str, incident_id: str, plan_json: str) -> dict:
    """Submit a remediation plan to the approval queue."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO approvals (plan_id, incident_id, plan_json) VALUES (?, ?, ?)",
        (plan_id, incident_id, plan_json),
    )
    conn.commit()
    conn.close()
    return {"plan_id": plan_id, "status": "pending"}


__all__ = ["init_db", "submit_plan", "get_connection", "DB_PATH"]