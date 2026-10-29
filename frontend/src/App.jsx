import { useCallback, useEffect, useMemo, useState } from "react";

import ApprovalQueue from "./components/ApprovalQueue.jsx";
import DiagnosisPanel from "./components/DiagnosisPanel.jsx";
import PipelineTracker from "./components/PipelineTracker.jsx";
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
    const detail = Array.isArray(body.detail)
      ? body.detail.map((item) => item.msg).join(" ")
      : body.detail;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return response.json();
}

function detectedAt(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

// "inc-case3-adversarial" -> "Case 3 · Adversarial"
function caseLabel(incidentId) {
  const match = /case(\d+)-(.+)$/.exec(incidentId || "");
  if (!match) return incidentId;
  const name = match[2].replaceAll("-", " ");
  return `Case ${match[1]} · ${name.charAt(0).toUpperCase()}${name.slice(1)}`;
}

const HEADER_STATUS = {
  ok: { text: "Diagnosed · OK", tone: "tone-good" },
  uncertain: { text: "Diagnosed · Uncertain", tone: "tone-warn" },
  insufficient_evidence: { text: "Insufficient evidence", tone: "tone-danger" },
  failed: { text: "Diagnosis failed", tone: "tone-danger" },
};

function headerStatus(report, busy, plan) {
  if (busy) return { text: "Investigating", tone: "tone-active" };
  if (!report && plan) return { text: "Plan saved · rerun triage", tone: "tone-warn" };
  if (!report) return { text: "Open", tone: "" };
  return HEADER_STATUS[report.status] || { text: "Diagnosed", tone: "tone-good" };
}

function Shield() {
  return (
    <svg viewBox="0 0 24 24" className="shield" aria-hidden="true">
      <path d="M12 2.5 20 5.5v6c0 5-3.4 8.6-8 10-4.6-1.4-8-5-8-10v-6l8-3Z" />
      <path d="M12 7.5v9M7.5 12h9M9 9l6 6M15 9l-6 6" />
    </svg>
  );
}

export default function App() {
  const [incidents, setIncidents] = useState([]);
  const [selectedIncidentId, setSelectedIncidentId] = useState("");
  const [reports, setReports] = useState({});
  const [plans, setPlans] = useState([]);
  const [selectedPlanId, setSelectedPlanId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const incident = incidents.find((item) => item.incident_id === selectedIncidentId) || null;
  const report = reports[selectedIncidentId] || null;
  const incidentPlans = useMemo(
    () => plans.filter((plan) => plan.incident_id === selectedIncidentId),
    [plans, selectedIncidentId],
  );
  const selectedPlan =
    incidentPlans.find((plan) => plan.plan_id === selectedPlanId) || incidentPlans[0] || null;

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
    } catch (loadError) {
      setError(`${loadError.message}. Is the backend running on port 8000?`);
    }
  }, []);

  useEffect(() => {
    loadWorkspace();
  }, [loadWorkspace]);

  async function runTriage() {
    if (!incident) return;
    setBusy(true);
    setError("");
    try {
      const result = await request("/api/incidents", {
        method: "POST",
        body: JSON.stringify({ incident_id: incident.incident_id }),
      });
      setReports((current) => ({ ...current, [incident.incident_id]: result.report }));
      if (result.plan?.plan_id) setSelectedPlanId(result.plan.plan_id);
      await loadWorkspace();
    } catch (triageError) {
      setError(triageError.message);
    } finally {
      setBusy(false);
    }
  }

  async function decide(action, reason) {
    if (!selectedPlan) return;
    setBusy(true);
    setError("");
    try {
      const updated = await request(`/api/approvals/${selectedPlan.plan_id}/${action}`, {
        method: "POST",
        body: action === "reject" ? JSON.stringify({ reason }) : undefined,
      });
      setPlans((current) => current.map((plan) => (plan.plan_id === updated.plan_id ? updated : plan)));
    } catch (actionError) {
      setError(actionError.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="IncidentPilot home">
          <Shield />
          <span>
            Incident<span className="brand-accent">Pilot</span>
          </span>
        </a>

        <nav aria-label="Incidents">
          <p className="nav-label">Incidents</p>
          <ul className="incident-nav">
            {incidents.map((item) => {
              const itemReport = reports[item.incident_id];
              const pending = plans.some(
                (plan) => plan.incident_id === item.incident_id && plan.status === "pending",
              );
              return (
                <li key={item.incident_id}>
                  <button
                    type="button"
                    className={`nav-item ${item.incident_id === selectedIncidentId ? "is-active" : ""}`}
                    onClick={() => setSelectedIncidentId(item.incident_id)}
                  >
                    <span className="nav-case">{caseLabel(item.incident_id)}</span>
                    <span className="nav-title">{item.alert.name}</span>
                    <span className="nav-sub">
                      {item.alert.service}
                      {itemReport && <span className={`dot dot-${itemReport.status}`} />}
                      {pending && <span className="nav-badge">plan</span>}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>

        <p className="sidebar-foot">
          Human approval required.
          <br />
          No action runs from this screen.
        </p>
      </aside>

      <main className="main">
        <header className="incident-head">
          {incident ? (
            <>
              <div>
                <p className="eyebrow">{incident.incident_id}</p>
                <h1>{incident.alert.name}</h1>
                <p className="muted">
                  {incident.alert.description || `Alert on ${incident.alert.service}`}
                </p>
              </div>
              <div className="incident-actions">
                <span className="muted small">Detected {detectedAt(incident.alert.fired_at)}</span>
                <span className={`live ${headerStatus(report, busy, selectedPlan).tone}`}>
                  {headerStatus(report, busy, selectedPlan).text}
                </span>
                {report && (
                  <button className="btn btn-ghost" onClick={runTriage} disabled={busy}>
                    {busy ? "Running triage…" : "Run triage again"}
                  </button>
                )}
              </div>
            </>
          ) : (
            <div>
              <h1>Incidents</h1>
              <p className="muted">Loading recorded incidents…</p>
            </div>
          )}
        </header>

        {incident && <PipelineTracker busy={busy} report={report} plan={selectedPlan} />}

        {error && <StatusBanner tone="danger" message={error} />}

        <div className="grid">
          <DiagnosisPanel
            report={report}
            busy={busy}
            incident={incident}
            onRunTriage={runTriage}
            hasPlan={incidentPlans.length > 0}
          />
          <div className="side">
            <ApprovalQueue
              plans={incidentPlans}
              selectedPlanId={selectedPlan?.plan_id}
              onSelect={setSelectedPlanId}
            />
            <PlanDetail
              key={selectedPlan?.plan_id || "none"}
              plan={selectedPlan}
              busy={busy}
              onApprove={() => decide("approve")}
              onReject={(reason) => decide("reject", reason)}
              hasDiagnosis={Boolean(report)}
            />
          </div>
        </div>
      </main>
    </div>
  );
}
