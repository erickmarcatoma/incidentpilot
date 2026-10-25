"""FastAPI app for the IncidentPilot approval screen."""

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.db import init_db, get_connection, DB_PATH
from backend.agents.remediation.agent import create_remediation_plan

app = FastAPI(title="IncidentPilot")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HealthResponse(BaseModel):
    status: str = "ok"


class ApprovalResponse(BaseModel):
    plan_id: str
    incident_id: str
    status: str
    steps: list[dict]
    risk: str
    rollback: str
    recovery_check: dict | None
    incident_summary: str
    diagnosis_status: str


@app.on_event("startup")
def startup():
    init_db()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/approvals/{plan_id}", response_model=ApprovalResponse)
def get_approval(plan_id: str) -> ApprovalResponse:
    conn = get_connection()
    row = conn.execute(
        "SELECT plan_json FROM approvals WHERE plan_id = ?",
        (plan_id,),
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Plan not found")

    plan_data = json.loads(row["plan_json"])
    return ApprovalResponse(**plan_data)


@app.get("/approvals/incident/{incident_id}")
def get_approvals_for_incident(incident_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT plan_json FROM approvals WHERE incident_id = ?",
        (incident_id,),
    ).fetchall()
    conn.close()

    return [json.loads(r["plan_json"]) for r in rows]


@app.post("/approvals/{plan_id}/approve")
def approve_plan(plan_id: str) -> dict:
    conn = get_connection()
    row = conn.execute(
        "UPDATE approvals SET status = ? WHERE plan_id = ?",
        ("approved", plan_id),
    ).rowcount
    conn.commit()
    conn.close()

    if row == 0:
        raise HTTPException(status_code=404, detail="Plan not found")

    return {"plan_id": plan_id, "status": "approved"}


@app.post("/approvals/{plan_id}/reject")
def reject_plan(plan_id: str, reason: str | None = None) -> dict:
    conn = get_connection()
    conn.execute(
        "UPDATE approvals SET status = ? WHERE plan_id = ?",
        ("rejected", plan_id),
    )
    conn.commit()
    conn.close()

    return {"plan_id": plan_id, "status": "rejected"}


__all__ = ["app"]