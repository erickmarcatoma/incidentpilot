import { useEffect, useState } from "react";

// The usual order of a triage run. The backend does not stream progress yet,
// so the steps advance on a timer and the last one waits until the report arrives.
const STEPS = [
  { label: "Reading metrics", detail: "get_metrics: what changed, and when" },
  { label: "Searching logs", detail: "search_logs: errors and warnings in the window" },
  { label: "Checking traces", detail: "get_traces: which service fails first" },
  { label: "Writing the report", detail: "Up to 3 ranked causes, each quoting evidence" },
  { label: "Checking every quote", detail: "Code verifies the evidence and sets the status" },
];
const STEP_SECONDS = 2.5;
const LIMIT_SECONDS = 90;

export default function TriageProgress({ incidentId }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => setElapsed((Date.now() - started) / 1000), 250);
    return () => clearInterval(timer);
  }, [incidentId]);

  const current = Math.min(Math.floor(elapsed / STEP_SECONDS), STEPS.length - 1);

  return (
    <section className="card triage-progress" aria-live="polite" aria-busy="true">
      <div className="card-head">
        <p className="section-label">Triage running · {incidentId}</p>
        <span className="muted small">
          {Math.floor(elapsed)} s · limit {LIMIT_SECONDS} s
        </span>
      </div>

      <ol className="progress-steps">
        {STEPS.map((step, index) => {
          const state = index < current ? "done" : index === current ? "active" : "todo";
          return (
            <li key={step.label} className={`progress-step is-${state}`}>
              <span className="progress-icon" aria-hidden="true">
                {state === "done" ? "✓" : state === "active" ? <span className="spinner" /> : index + 1}
              </span>
              <span>
                <strong>{step.label}</strong>
                <small>{step.detail}</small>
              </span>
            </li>
          );
        })}
      </ol>

      <div className="progress-bar" aria-hidden="true">
        <span style={{ width: `${Math.min((elapsed / LIMIT_SECONDS) * 100, 100)}%` }} />
      </div>
      <p className="muted small">
        The agent can only read data. Nothing in production changes during triage.
      </p>
    </section>
  );
}
