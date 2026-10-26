function statusLabel(status) {
  return (status || "pending").replaceAll("_", " ");
}

export default function ApprovalQueue({ plans, selectedPlanId, onSelect }) {
  return (
    <section className="panel queue-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">HUMAN REVIEW</p>
          <h2>Approval queue</h2>
        </div>
        <span className="queue-count">{plans.length}</span>
      </div>
      {plans.length === 0 ? (
        <p className="empty-state">
          No remediation plans are waiting. Triage reports appear here after a plan is
          submitted.
        </p>
      ) : (
        <ul className="queue-list">
          {plans.map((plan) => (
            <li key={plan.plan_id}>
              <button
                className={`queue-item ${
                  selectedPlanId === plan.plan_id ? "is-selected" : ""
                }`}
                onClick={() => onSelect(plan.plan_id)}
              >
                <span className="queue-item-main">
                  <strong>{plan.incident_summary}</strong>
                  <small>{plan.incident_id}</small>
                </span>
                <span className={`status-pill status-${plan.status}`}>
                  {statusLabel(plan.status)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}