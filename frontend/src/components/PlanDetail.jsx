import { useState } from "react";

const POLICY_COPY = {
  allowed: { tone: "good", text: "Policy: allowed" },
  requires_approval: { tone: "warn", text: "Policy: approval required" },
  rejected: { tone: "danger", text: "Policy: rejected" },
};

function label(value) {
  return (value || "").replaceAll("_", " ");
}

function fileName(path) {
  return (path || "").split(/[\\/]/).pop();
}

export default function PlanDetail({ plan, busy, onApprove, onReject, hasDiagnosis }) {
  const [rejecting, setRejecting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState("");

  if (!plan) {
    return (
      <section className={`card empty ${hasDiagnosis ? "" : "is-waiting"}`}>
        <p className="section-label">Remediation plan</p>
        <h2>{hasDiagnosis ? "No plan yet" : "Waiting for diagnosis"}</h2>
        <p className="muted">
          {hasDiagnosis
            ? "The Remediation Agent turns the validated diagnosis into a plan here. Nothing runs until a person approves it."
            : "A plan appears here after triage and validation. Nothing runs until a person approves it."}
        </p>
      </section>
    );
  }

  const canDecide = plan.status === "pending";

  function submitReject(event) {
    event.preventDefault();
    const trimmed = reason.trim();
    if (!trimmed) return;
    onReject(trimmed);
    setReason("");
    setRejecting(false);
  }

  return (
    <section className="card plan">
      <div className="card-head">
        <h2 className="plan-title">
          <span className="plan-icon" aria-hidden="true">&lt;/&gt;</span> Remediation plan
        </h2>
        <span className={`chip chip-status-${plan.status}`}>{label(plan.status)}</span>
      </div>

      {plan.diagnosis_status === "uncertain" && plan.addresses_hypothesis && (
        <p className="pill-line warn">
          Uncertain diagnosis: plans for {plan.addresses_hypothesis}
          {plan.alternative_hypothesis ? `, alternative ${plan.alternative_hypothesis}` : ""}
        </p>
      )}

      <p className="plan-summary">{plan.incident_summary}</p>

      {plan.status === "needs_human" ? (
        <div className="note note-danger">
          <span className="section-label">Needs a human</span>
          <p>{plan.reason || "No safe automated step was found."}</p>
        </div>
      ) : (
        <>
          <p className="muted small">
            Addresses <strong>{plan.addresses_hypothesis}</strong>
          </p>
          <ol className="steps">
            {plan.steps.map((step, index) => {
              const policy = POLICY_COPY[step.policy_result] || { tone: "neutral", text: label(step.policy_result) };
              return (
                <li key={`${step.action}-${index}`}>
                  <span className="step-number">{index + 1}</span>
                  <div className="step-body">
                    <strong>{label(step.action)}</strong>
                    <span className="muted small">{step.target_service}</span>
                    {step.runbook_step && <span className="muted small">{step.runbook_step}</span>}
                  </div>
                  <span className={`chip chip-${policy.tone}`}>{policy.text}</span>
                </li>
              );
            })}
          </ol>
        </>
      )}

      {plan.runbook && (
        <div className="cite">
          <span className="section-label">Runbook citation</span>
          <div className="cite-row">
            <span className="cite-icon" aria-hidden="true">▤</span>
            <div>
              <strong>{fileName(plan.runbook.file)}</strong>
              <span className="muted small">{plan.runbook.section}</span>
            </div>
          </div>
        </div>
      )}

      {(plan.rollback || plan.risk) && (
        <dl className="facts">
          {plan.risk && (
            <div>
              <dt>Risk</dt>
              <dd>{plan.risk}</dd>
            </div>
          )}
          {plan.rollback && (
            <div>
              <dt>Rollback</dt>
              <dd>{plan.rollback}</dd>
            </div>
          )}
        </dl>
      )}

      {plan.recovery_check && (
        <div className="recovery">
          <span className="recovery-icon" aria-hidden="true">✓</span>
          <div>
            <strong>Recovery check</strong>
            <span className="muted small">
              {plan.recovery_check.metric} on {plan.recovery_check.service} back under{" "}
              {plan.recovery_check.threshold} within {plan.recovery_check.within_minutes} min
            </span>
          </div>
        </div>
      )}

      {canDecide && !rejecting && !confirming && (
        <div className="actions">
          <button className="btn btn-approve" onClick={() => setConfirming(true)} disabled={busy}>
            ✓ Approve
          </button>
          <button className="btn btn-ghost" onClick={() => setRejecting(true)} disabled={busy}>
            ✕ Reject
          </button>
        </div>
      )}

      {canDecide && confirming && (
        <div className="confirm" role="alertdialog" aria-labelledby="confirm-title">
          <strong id="confirm-title">Approve this plan?</strong>
          {plan.steps.length > 0 ? (
            <ul className="confirm-list">
              {plan.steps.map((step, index) => (
                <li key={`${step.action}-${index}`}>
                  Will run <code>{step.action}</code> on <strong>{step.target_service}</strong>
                </li>
              ))}
            </ul>
          ) : (
            <p>This plan has no automated steps.</p>
          )}
          {plan.rollback && (
            <p className="muted small">
              <strong>Rollback:</strong> {plan.rollback}
            </p>
          )}
          {plan.recovery_check && (
            <p className="muted small">
              <strong>Then checks:</strong> {plan.recovery_check.metric} on {plan.recovery_check.service} within{" "}
              {plan.recovery_check.within_minutes} min
            </p>
          )}
          {plan.diagnosis_status !== "ok" && (
            <p className="confirm-warn">
              The diagnosis is <strong>{label(plan.diagnosis_status)}</strong>. Check the alternative before approving.
            </p>
          )}
          <div className="actions">
            <button
              className="btn btn-approve"
              onClick={() => {
                setConfirming(false);
                onApprove();
              }}
              disabled={busy}
              autoFocus
            >
              Yes, approve
            </button>
            <button className="btn btn-ghost" onClick={() => setConfirming(false)} disabled={busy}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {canDecide && rejecting && (
        <form className="reject" onSubmit={submitReject}>
          <label htmlFor="reject-reason">Why are you rejecting this plan?</label>
          <textarea
            id="reject-reason"
            rows="3"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            required
          />
          <div className="actions">
            <button className="btn btn-danger" disabled={busy || !reason.trim()}>
              Confirm reject
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => setRejecting(false)} disabled={busy}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {!canDecide && plan.status === "rejected" && plan.reason && (
        <p className="muted small">Rejected: {plan.reason}</p>
      )}

      <p className="safety">Approving records your decision. Only the executor runs actions.</p>
    </section>
  );
}
