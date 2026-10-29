from fastapi.testclient import TestClient

from backend import db
from backend.agents.triage.tools import load_incident_packet
from backend.main import app
from backend.schemas import (
    Category,
    DiagnosisStatus,
    Evidence,
    EvidenceSource,
    Hypothesis,
    PlanStep,
    PlanStatus,
    PolicyResult,
    RecoveryCheck,
    RemediationPlan,
    RootCauseReport,
    RunbookRef,
)


def pending_plan() -> RemediationPlan:
    return RemediationPlan(
        incident_id="inc-case1-payment",
        addresses_hypothesis="H1",
        runbook=RunbookRef(file="payment-service-failure.md", section="Recovery"),
        steps=[
            PlanStep(
                action="restart_service",
                target_service="payment",
                policy_result=PolicyResult.ALLOWED,
                runbook_step="Restart the payment service.",
            )
        ],
        risk="Brief payment interruption.",
        rollback="Restore the previous service configuration.",
        recovery_check=RecoveryCheck(
            metric="error_rate",
            service="payment",
            threshold=0.05,
        ),
        incident_summary="Recover payment authorization failures.",
        diagnosis_status=DiagnosisStatus.OK,
        status=PlanStatus.PENDING,
    )


def case1_report() -> RootCauseReport:
    packet = load_incident_packet("inc-case1-payment")
    payment_log = next(
        entry for entry in packet.logs if entry.service == "payment" and entry.severity == "error"
    )
    return RootCauseReport(
        incident_id=packet.incident_id,
        window=packet.window,
        affected_services=["payment"],
        hypotheses=[
            Hypothesis(
                id="H1",
                cause="Invalid payment token",
                category=Category.SERVICE_FAILURE,
                service="payment",
                confidence=0.9,
                evidence=[
                    Evidence(
                        source=EvidenceSource.LOGS,
                        ref=payment_log.ref,
                        quote=payment_log.message,
                    )
                ],
            )
        ],
        status=DiagnosisStatus.OK,
    )


def test_incident_fixture_routes(monkeypatch, tmp_path):
    monkeypatch.setenv("INCIDENTPILOT_DB_PATH", str(tmp_path / "approvals.sqlite3"))
    with TestClient(app) as client:
        incidents = client.get("/api/incidents")
        case1 = client.get("/api/incidents/inc-case1-payment")
        missing = client.get("/api/incidents/unknown")

    assert incidents.status_code == 200
    assert {item["incident_id"] for item in incidents.json()} == {
        "inc-case1-payment",
        "inc-case2-memory-leak",
        "inc-case3-adversarial",
    }
    assert case1.status_code == 200
    assert case1.json()["incident_id"] == "inc-case1-payment"
    assert missing.status_code == 404


def test_incident_submission_returns_agent_report(monkeypatch, tmp_path):
    monkeypatch.setenv("INCIDENTPILOT_DB_PATH", str(tmp_path / "approvals.sqlite3"))
    packet = load_incident_packet("inc-case1-payment")

    def fake_run_triage(received_packet):
        assert received_packet.incident_id == packet.incident_id
        return case1_report()

    monkeypatch.setattr("backend.main.run_triage", fake_run_triage)
    with TestClient(app) as client:
        response = client.post("/api/incidents", json=packet.model_dump(mode="json"))

    assert response.status_code == 200
    body = response.json()
    assert body["report"]["incident_id"] == packet.incident_id
    plan = body["plan"]
    assert plan["status"] == "pending"
    assert [(s["action"], s["target_service"]) for s in plan["steps"]] == [("toggle_feature_flag", "payment")]
    assert plan["plan_id"]


def test_new_triage_supersedes_the_older_pending_plan(monkeypatch, tmp_path):
    monkeypatch.setenv("INCIDENTPILOT_DB_PATH", str(tmp_path / "approvals.sqlite3"))
    packet = load_incident_packet("inc-case1-payment")
    monkeypatch.setattr("backend.main.run_triage", lambda received_packet: case1_report())
    with TestClient(app) as client:
        first = client.post("/api/incidents", json=packet.model_dump(mode="json")).json()["plan"]
        second = client.post("/api/incidents", json=packet.model_dump(mode="json")).json()["plan"]
        queue = {p["plan_id"]: p["status"] for p in client.get("/api/approvals").json()}

    assert queue[first["plan_id"]] == "superseded"
    assert queue[second["plan_id"]] == "pending"


def test_approval_queue_records_decisions_without_execution(monkeypatch, tmp_path):
    database = tmp_path / "approvals.sqlite3"
    monkeypatch.setenv("INCIDENTPILOT_DB_PATH", str(database))
    with TestClient(app) as client:
        saved = db.insert_plan(pending_plan())
        listed = client.get("/api/approvals")
        approved = client.post(f"/api/approvals/{saved.plan_id}/approve")
        repeated = client.post(f"/api/approvals/{saved.plan_id}/approve")
        missing = client.get("/api/approvals/no-such-plan")

    assert listed.status_code == 200
    assert listed.json()[0]["plan_id"] == saved.plan_id
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert repeated.status_code == 409
    assert missing.status_code == 404


def test_reject_requires_a_nonblank_reason(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "INCIDENTPILOT_DB_PATH",
        str(tmp_path / "approvals.sqlite3"),
    )
    with TestClient(app) as client:
        saved = db.insert_plan(pending_plan())
        rejected = client.post(
            f"/api/approvals/{saved.plan_id}/reject",
            json={"reason": "Need a safer recovery step"},
        )
        blank_reason = client.post(
            f"/api/approvals/{saved.plan_id}/reject",
            json={"reason": "   "},
        )

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["reason"] == "Need a safer recovery step"
    assert blank_reason.status_code == 422
