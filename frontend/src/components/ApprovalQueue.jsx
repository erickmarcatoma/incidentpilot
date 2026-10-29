function label(value) {
  return (value || "").replaceAll("_", " ");
}

export default function ApprovalQueue({ plans, selectedPlanId, onSelect }) {
  if (plans.length <= 1) return null;

  return (
    <section className="queue">
      <p className="section-label">Approval queue · {plans.length}</p>
      <ul>
        {plans.map((plan) => (
          <li key={plan.plan_id}>
            <button
              type="button"
              className={`queue-item ${plan.plan_id === selectedPlanId ? "is-selected" : ""}`}
              onClick={() => onSelect(plan.plan_id)}
            >
              <span>{plan.addresses_hypothesis || "—"}</span>
              <span className="queue-summary">{plan.incident_summary}</span>
              <span className={`chip chip-status-${plan.status}`}>{label(plan.status)}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
