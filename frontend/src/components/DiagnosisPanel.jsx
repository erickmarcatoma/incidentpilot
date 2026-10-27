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

function formatTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function IncidentOverview({ incident, busy, onRunTriage }) {
  const sources = [
    { label: "Metrics", count: incident.metrics?.length ?? 0 },
    { label: "Logs", count: incident.logs?.length ?? 0 },
    { label: "Traces", count: incident.traces?.length ?? 0 },
  ];
  const missing = sources.filter((source) => source.count === 0);

  return (
    <section className="card overview">
      <p className="section-label">Before triage</p>
      <dl className="overview-facts">
        <div>
          <dt>Alert</dt>
          <dd>
            {incident.alert.name} on <strong>{incident.alert.service}</strong>
          </dd>
        </div>
        <div>
          <dt>Window</dt>
          <dd>
            {formatTime(incident.window.start)} – {formatTime(incident.window.end)}
          </dd>
        </div>
        <div>
          <dt>Services</dt>
          <dd className="service-tags">
            {incident.services.map((service) => (
              <span className="tag" key={service}>
                {service}
              </span>
            ))}
          </dd>
        </div>
      </dl>

      <div>
        <span className="section-label">Data available</span>
        <div className="source-counts">
          {sources.map((source) => (
            <div key={source.label} className={`source-count ${source.count === 0 ? "is-missing" : ""}`}>
              <strong>{source.count}</strong>
              <span>{source.label}</span>
            </div>
          ))}
        </div>
        {missing.length > 0 && (
          <p className="missing-note">
            No {missing.map((source) => source.label.toLowerCase()).join(" or ")} for this incident. The
            diagnosis cannot be marked OK.
          </p>
        )}
      </div>

      <div className="overview-action">
        <p className="muted small">
          The Triage Agent reads this data and ranks up to 3 causes. Every cause must quote evidence
          that exists here.
        </p>
        <button className="btn btn-primary" onClick={onRunTriage} disabled={busy}>
          {busy ? "Running triage…" : "Run triage"}
        </button>
      </div>
    </section>
  );
}

export default function DiagnosisPanel({ report, busy, incident, onRunTriage }) {
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

  if (!report && incident) {
    return <IncidentOverview incident={incident} busy={busy} onRunTriage={onRunTriage} />;
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
