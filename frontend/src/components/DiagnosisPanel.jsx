import { useState } from "react";

import StatusBanner from "./StatusBanner.jsx";

function label(value) {
  return (value || "").replaceAll("_", " ");
}

function confidenceTone(confidence) {
  if (confidence >= 0.7) return "good";
  if (confidence >= 0.5) return "warn";
  return "danger";
}

function HypothesisCard({ hypothesis, leading }) {
  return (
    <article className={`hypothesis ${leading ? "is-leading" : ""}`}>
      <header className="hypothesis-head">
        <span className="hypothesis-icon" aria-hidden="true">⚠</span>
        <h3>
          <span className="hypothesis-id">{hypothesis.id}:</span> {hypothesis.cause}
        </h3>
        <span className={`chip chip-${confidenceTone(hypothesis.confidence)}`}>
          Confidence {hypothesis.confidence.toFixed(2)}
        </span>
      </header>
      <p className="hypothesis-meta">
        <span className="tag">{label(hypothesis.category)}</span>
        <span className="tag">{hypothesis.service}</span>
      </p>
      <div className="evidence">
        <span className="section-label">Evidence</span>
        <ul className="evidence-list">
          {hypothesis.evidence.map((evidence) => (
            <li key={`${evidence.source}-${evidence.ref}-${evidence.quote}`}>
              <span className="evidence-ref">{evidence.ref}</span>
              <span className="evidence-source">{evidence.source}</span>
              <code className="evidence-quote">{evidence.quote}</code>
            </li>
          ))}
        </ul>
      </div>
    </article>
  );
}

export default function DiagnosisPanel({ report, busy }) {
  const [showAlternatives, setShowAlternatives] = useState(false);

  if (busy && !report) {
    return (
      <section className="card">
        <p className="section-label">Diagnosis</p>
        <div className="loading">
          <span className="spinner" aria-hidden="true" />
          Triage agent is reading metrics, logs and traces…
        </div>
      </section>
    );
  }

  if (!report) {
    return (
      <section className="card empty">
        <p className="section-label">Diagnosis</p>
        <h2>No diagnosis yet</h2>
        <p className="muted">
          Run triage on an incident. Every cause it reports must quote evidence that exists
          in the telemetry.
        </p>
      </section>
    );
  }

  const [leading, ...alternatives] = report.hypotheses;
  const uncertain = report.status === "uncertain";
  const sideBySide = uncertain && alternatives.length > 0;

  return (
    <section className="card diagnosis">
      <div className="card-head">
        <p className="section-label">Diagnosis · {report.incident_id}</p>
        <span className="muted small">{report.affected_services.join(", ")}</span>
      </div>

      <StatusBanner status={report.status} />

      {leading ? (
        sideBySide ? (
          <div className="compare">
            <HypothesisCard hypothesis={leading} leading />
            <HypothesisCard hypothesis={alternatives[0]} />
          </div>
        ) : (
          <HypothesisCard hypothesis={leading} leading />
        )
      ) : null}

      {alternatives.length > (sideBySide ? 1 : 0) && (
        <div className="alternatives">
          <button
            type="button"
            className="link-button"
            onClick={() => setShowAlternatives((open) => !open)}
            aria-expanded={showAlternatives}
          >
            {showAlternatives ? "Hide" : "Show"} other hypotheses (
            {alternatives.length - (sideBySide ? 1 : 0)})
          </button>
          {showAlternatives &&
            alternatives
              .slice(sideBySide ? 1 : 0)
              .map((hypothesis) => <HypothesisCard key={hypothesis.id} hypothesis={hypothesis} />)}
        </div>
      )}

      {report.unknowns?.length > 0 && (
        <div className="note note-warn">
          <span className="section-label">Unknowns</span>
          <ul>
            {report.unknowns.map((unknown) => (
              <li key={unknown}>{unknown}</li>
            ))}
          </ul>
        </div>
      )}

      {report.validation_notes?.length > 0 && (
        <div className="note">
          <span className="section-label">Validation notes</span>
          <ul>
            {report.validation_notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
