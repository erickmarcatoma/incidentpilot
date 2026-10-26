import { useState } from "react";

export default function PlanDetail({ plan, busy, onApprove, onReject }) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");

  if (!plan) return null;

  const canDecide = plan.status === "pending";

  function rejectPlan(event) {
    event.preventDefault();
    const trimmedReason = reason.trim();
    if (!trimmedReason) return;
    onReject(trimmedReason);
    setReason("");
    setRejecting(false);
  }

  return (
    <section className="panel plan-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">PLAN DETAILS</p>
          <h2>Proposed remediation</h2>
        </div>
        <span className={`status-pill status-${plan.status}`}>
          {plan.status.replaceAll("_", " ")}
        </span>
      </div>
      <p className="plan-summary">{plan.incident_summary}</p>
      <dl className="plan-facts">
        <div>
          <dt>Addresses</dt>
          <dd>{plan.addresses_hypothesis || "Needs human review"}</dd>
        </div>
        <div>
          <dt>Diagnosis</dt>
          <dd>{plan.diagnosis_status.replaceAll("_", " ")}</dd>
        </div>
        {plan.runbook && (
          <div>
            <dt>Runbook</dt>
            <dd>
              {plan.runbook.file} / {plan.runbook.section}
            </dd>
          </div>
        )}
      </dl>
      {plan.steps.length > 0 && (
        <div className="plan-steps">
          <span className="field-label">Steps</span>
          <ol>
            {plan.steps.map((step, index) => (
              <li key={`${step.action}-${index}`}>
                <strong>{step.action.replaceAll("_", " ")}</strong>
                <span>
                  {step.target_service} · {step.policy_result.replaceAll("_", " ")}
                </span>
                {step.runbook_step && <small>{step.runbook_step}</small>}
              </li>
            ))}
          </ol>
        </div>
      )}
      {plan.reason && <p className="plan-reason">{plan.reason}</p>}
      {canDecide && !rejecting && (
        <div className="plan-actions">
          <button className="button button-primary" onClick={onApprove} disabled={busy}>
            Approve plan
          </button>
          <button
            className="button button-danger"
            onClick={() => setRejecting(true)}
            disabled={busy}
          >
            Reject
          </button>
        </div>
      )}
      {canDecide && rejecting && (
        <form className="reject-form" onSubmit={rejectPlan}>
          <label htmlFor="reject-reason">Reason for rejection</label>
          <textarea
            id="reject-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows="3"
            required
          />
          <div className="plan-actions">
            <button className="button button-danger" disabled={busy || !reason.trim()}>
              Confirm rejection
            </button>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => setRejecting(false)}
              disabled={busy}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
      <p className="safety-note">Approval records your decision; it does not run actions.</p>
    </section>
  );
}