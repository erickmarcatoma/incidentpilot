const STEPS = [
  { key: "triage", label: "Triage", hint: "Agent reads telemetry" },
  { key: "validate", label: "Validate", hint: "Code checks the evidence" },
  { key: "plan", label: "Plan", hint: "Runbook + policy" },
  { key: "approve", label: "Approve", hint: "A person decides" },
];

const STATUS_TEXT = {
  ok: "Diagnosis OK",
  uncertain: "Uncertain",
  insufficient_evidence: "Insufficient evidence",
  failed: "Failed",
};

const PLAN_TEXT = {
  approved: "Approved",
  rejected: "Rejected",
  executed: "Executed",
  recovered: "Recovered",
  not_recovered: "Not recovered",
};

const STATUS_TONE = {
  ok: "good",
  uncertain: "warn",
  insufficient_evidence: "danger",
  failed: "danger",
};

function stepStates({ busy, report, plan }) {
  // A saved plan proves triage and validation already ran, even after a page reload.
  const diagnosis = report?.status || plan?.diagnosis_status || null;
  const diagnosed = Boolean(report || plan);
  const decided = plan && Object.keys(PLAN_TEXT).includes(plan.status);
  const states = {
    triage: diagnosed ? "done" : busy ? "active" : "next",
    validate: diagnosis ? "done" : "todo",
    plan: plan ? "done" : diagnosis ? "active" : "todo",
    approve: decided ? "done" : plan ? "active" : "todo",
  };
  const tones = { validate: diagnosis ? STATUS_TONE[diagnosis] : null };
  if (plan?.status === "needs_human") tones.plan = "warn";
  if (plan?.status === "rejected") tones.approve = "danger";
  return { states, tones, diagnosis };
}

export default function PipelineTracker({ busy, report, plan }) {
  const { states, tones, diagnosis } = stepStates({ busy, report, plan });
  return (
    <ol className="pipeline" aria-label="Incident pipeline">
      {STEPS.map((step, index) => {
        const state = states[step.key];
        const tone = tones[step.key];
        return (
          <li key={step.key} className={`pipe-step is-${state} ${tone ? `tone-${tone}` : ""}`}>
            <span className="pipe-dot" aria-hidden="true">
              {state === "done" ? "✓" : index + 1}
            </span>
            <span className="pipe-text">
              <strong>{step.label}</strong>
              <small>
                {step.key === "validate" && diagnosis
                  ? STATUS_TEXT[diagnosis] || diagnosis
                  : step.key === "plan" && plan?.status === "needs_human"
                    ? "Needs a human"
                    : step.key === "approve" && plan && states.approve === "done"
                      ? PLAN_TEXT[plan.status] || plan.status
                      : step.hint}
              </small>
            </span>
            {index < STEPS.length - 1 && <span className="pipe-line" aria-hidden="true" />}
            <span className="visually-hidden">{state}</span>
          </li>
        );
      })}
    </ol>
  );
}
