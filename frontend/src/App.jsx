import { useCallback, useEffect, useState } from "react";

import ApprovalQueue from "./components/ApprovalQueue.jsx";
import DiagnosisPanel from "./components/DiagnosisPanel.jsx";
import PlanDetail from "./components/PlanDetail.jsx";
import StatusBanner from "./components/StatusBanner.jsx";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

async function request(path, options) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

export default function App() {
  const [incidents, setIncidents] = useState([]);
  const [selectedIncidentId, setSelectedIncidentId] = useState("");
  const [report, setReport] = useState(null);
  const [plans, setPlans] = useState([]);
  const [selectedPlanId, setSelectedPlanId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selectedPlan = plans.find((plan) => plan.plan_id === selectedPlanId) || null;

  const loadWorkspace = useCallback(async () => {
    setError("");
    try {
      const [incidentData, planData] = await Promise.all([
        request("/api/incidents"),
        request("/api/approvals"),
      ]);
      setIncidents(incidentData);
      setPlans(planData);
      setSelectedIncidentId((current) => current || incidentData[0]?.incident_id || "");
      setSelectedPlanId((current) =>
        planData.some((plan) => plan.plan_id === current)
          ? current
          : planData[0]?.plan_id || "",
      );
    } catch (loadError) {
      setError(loadError.message);
    }
  }, []);

  useEffect(() => {
    loadWorkspace();
  }, [loadWorkspace]);

  async function runTriage() {
    if (!selectedIncidentId) return;
    setBusy(true);
    setError("");
    setReport(null);
    try {
      const packet = await request(`/api/incidents/${selectedIncidentId}`);
      const result = await request("/api/incidents", {
        method: "POST",
        body: JSON.stringify(packet),
      });
      setReport(result.report);
      await loadWorkspace();
    } catch (triageError) {
      setError(triageError.message);
    } finally {
      setBusy(false);
    }
  }

  async function transitionPlan(action, reason) {
    if (!selectedPlanId) return;
    setBusy(true);
    setError("");
    try {
      const updated = await request(
        `/api/approvals/${selectedPlanId}/${action}`,
        {
          method: "POST",
          body: action === "reject" ? JSON.stringify({ reason }) : undefined,
        },
      );
      setPlans((current) =>
        current.map((plan) => (plan.plan_id === updated.plan_id ? updated : plan)),
      );
    } catch (actionError) {
      setError(actionError.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="IncidentPilot home">
          <span className="brand-mark">IP</span>
          <span>IncidentPilot</span>
        </a>
        <span className="topbar-caption">Incident response workspace</span>
      </header>

      <section className="page-heading">
        <div>
          <p className="eyebrow">CONTROL ROOM / TRIAGE</p>
          <h1>Incident review</h1>
          <p className="page-subtitle">
            Inspect the diagnosis, then review any remediation plan before action.
          </p>
        </div>
        <button className="button button-secondary" onClick={loadWorkspace}>
          Refresh
        </button>
      </section>

      {error && <StatusBanner tone="error" message={error} />}

      <section className="workspace-grid">
        <div className="primary-column">
          <section className="panel incident-panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">INVESTIGATION</p>
                <h2>Recorded incident</h2>
              </div>
              <span className="step-badge">01</span>
            </div>
            <div className="incident-controls">
              <label htmlFor="incident-select">Choose a fixture</label>
              <div className="control-row">
                <select
                  id="incident-select"
                  value={selectedIncidentId}
                  onChange={(event) => {
                    setSelectedIncidentId(event.target.value);
                    setReport(null);
                  }}
                  disabled={busy}
                >
                  {incidents.map((incident) => (
                    <option key={incident.incident_id} value={incident.incident_id}>
                      {incident.alert.name} · {incident.incident_id}
                    </option>
                  ))}
                </select>
                <button
                  className="button button-primary"
                  onClick={runTriage}
                  disabled={busy || !selectedIncidentId}
                >
                  {busy ? "Working…" : "Run triage"}
                </button>
              </div>
            </div>
            {selectedIncidentId && (
              <div className="incident-meta">
                <span>
                  Alert{" "}
                  <strong>
                    {incidents.find((item) => item.incident_id === selectedIncidentId)
                      ?.alert.name || selectedIncidentId}
                  </strong>
                </span>
                <span>Evidence checked against recorded telemetry</span>
              </div>
            )}
          </section>

          <DiagnosisPanel report={report} />
        </div>

        <aside className="secondary-column">
          <ApprovalQueue
            plans={plans}
            selectedPlanId={selectedPlanId}
            onSelect={setSelectedPlanId}
          />
          <PlanDetail
            plan={selectedPlan}
            busy={busy}
            onApprove={() => transitionPlan("approve")}
            onReject={(reason) => transitionPlan("reject", reason)}
          />
        </aside>
      </section>

      <footer className="page-footer">
        <span>Human approval required · No actions run from this screen</span>
        <span>IncidentPilot / 2026</span>
      </footer>
    </main>
  );
}