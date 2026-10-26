"""FastAPI application for fixture-backed triage and plan approvals."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal

from anthropic import APIError
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from backend import db
from backend.agents.triage.agent import (
    TriageAgentError,
    TriageConfigurationError,
    run_triage,
)
from backend.agents.triage.tools import list_incident_packets, load_incident_packet
from backend.schemas import IncidentPacket, PlanStatus, RemediationPlan, RootCauseReport


class IncidentResponse(BaseModel):
    report: RootCauseReport
    plan: RemediationPlan | None = None


class RejectRequest(BaseModel):
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, reason: str) -> str:
        reason = reason.strip()
        if not reason:
            raise ValueError("reason must not be blank")
        return reason


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.initialize_database()
    yield


app = FastAPI(
    title="IncidentPilot API",
    description="Fixture-backed incident triage and human plan approvals.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/incidents", response_model=list[IncidentPacket])
def incidents() -> list[IncidentPacket]:
    return list_incident_packets()


@app.get("/api/incidents/{incident_id}", response_model=IncidentPacket)
def incident(incident_id: str) -> IncidentPacket:
    try:
        return load_incident_packet(incident_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/incidents", response_model=IncidentResponse)
def create_incident_report(packet: IncidentPacket) -> IncidentResponse:
    try:
        return IncidentResponse(report=run_triage(packet))
    except TriageConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except TriageAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except APIError as exc:
        raise HTTPException(status_code=502, detail="Anthropic request failed") from exc


@app.get("/api/approvals", response_model=list[RemediationPlan])
def approvals() -> list[RemediationPlan]:
    return db.list_plans()


@app.get("/api/approvals/{plan_id}", response_model=RemediationPlan)
def approval(plan_id: str) -> RemediationPlan:
    plan = db.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Approval plan not found")
    return plan


def _transition_plan(
    plan_id: str,
    status: Literal["approved", "rejected"],
    reason: str | None = None,
) -> RemediationPlan:
    requested_status = PlanStatus(status)
    plan = db.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Approval plan not found")
    if plan.status is not PlanStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Plan cannot be {status}; current status is {plan.status.value}",
        )
    updated = db.update_plan_status(plan_id, requested_status, reason=reason)
    if updated is None:
        raise HTTPException(status_code=404, detail="Approval plan not found")
    if updated.status is not requested_status:
        raise HTTPException(
            status_code=409,
            detail=f"Plan cannot be {status}; current status is {updated.status.value}",
        )
    return updated


@app.post("/api/approvals/{plan_id}/approve", response_model=RemediationPlan)
def approve_plan(plan_id: str) -> RemediationPlan:
    return _transition_plan(plan_id, "approved")


@app.post("/api/approvals/{plan_id}/reject", response_model=RemediationPlan)
def reject_plan(plan_id: str, request: RejectRequest) -> RemediationPlan:
    return _transition_plan(plan_id, "rejected", reason=request.reason)