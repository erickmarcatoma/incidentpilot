import { useState } from "react";

import StatusBanner from "./StatusBanner.jsx";
import TriageProgress from "./TriageProgress.jsx";

function label(value) {
  return (value || "").replaceAll("_", " ");
}

function confidenceTone(confidence) {
  if (confidence >= 0.7) return "good";
  if (confidence >= 0.5) return "warn";
  return "danger";
}

// Text the agent uses when it flags untrusted telemetry, or that looks like an instruction.
const UNTRUSTED_PATTERN =
  /untrusted|instruction-like|ignore (all |previous |prior )?instructions|prompt injection|SYSTEM:/i;

function isUntrusted(text) {
  return UNTRUSTED_PATTERN.test(text || "");
}

// Re-check each quote against the incident data in the browser, so the badge is not just trust.
function verifyEvidence(evidence, incident) {
  if (!incident) return { state: "checked", text: "Checked by orchestrator" };
  if (evidence.source === "logs") {
    const log = incident.logs?.find((entry) => entry.ref === evidence.ref);
    if (!log) return { state: "missing", text: `${evidence.ref} not found` };
    if (!log.message.includes(evidence.quote)) return { state: "missing", text: "Quote not in log" };
    return { state: "verified", text: "Verified in log", untrustedSource: isUntrusted(log.message) };
  }
  if (evidence.source === "metrics") {
    const series = incident.metrics?.find((item) => item.ref === evidence.ref);
    return series
      ? { state: "verified", text: "Found in metrics" }
      : { state: "missing", text: `${evidence.ref} not found` };
  }
  const trace = incident.traces?.find((item) => item.ref === evidence.ref);
  return trace
    ? { state: "verified", text: "Found in traces" }
    : { state: "missing", text: `${evidence.ref} not found` };
}

function UntrustedTag() {
  return (
    <span className="untrusted-tag" title="Text from telemetry that reads like an instruction. Treated as data, never followed.">
      ⚠ Untrusted
    </span>
  );
}

function HypothesisCard({ hypothesis, leading, incident }) {
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
              <EvidenceBadge evidence={evidence} incident={incident} />
            </li>
          ))}
        </ul>
      </div>
    </article>
  );
}

function EvidenceBadge({ evidence, incident }) {
  const check = verifyEvidence(evidence, incident);
  return (
    <span className="evidence-badges">
      <span
        className={`verify-badge is-${check.state}`}
        title={check.state === "verified" ? `The quote exists in ${evidence.ref}` : check.text}
      >
        {check.state === "missing" ? "✕" : "✓"} {check.text}
      </span>
      {check.untrustedSource && <UntrustedTag />}
    </span>
  );
}

function Timeline({ events }) {
  const [open, setOpen] = useState(false);
  if (!events?.length) return null;
  const flagged = events.filter((event) => isUntrusted(event.event)).length;
  const shown = open ? events : events.filter((event) => isUntrusted(event.event));

  return (
    <div className="timeline">
      <div className="timeline-head">
        <span className="section-label">Timeline · {events.length} events</span>
        <button type="button" className="link-button" onClick={() => setOpen((value) => !value)}>
          {open ? "Show flagged only" : "Show all"}
        </button>
      </div>
      {flagged > 0 && !open && (
        <p className="muted small">
          {flagged} event{flagged > 1 ? "s" : ""} flagged as untrusted. The agent reported{" "}
          {flagged > 1 ? "them" : "it"} and did not act on {flagged > 1 ? "them" : "it"}.
        </p>
      )}
      {shown.length > 0 && (
        <ol className="timeline-list">
          {shown.map((event) => (
            <li key={`${event.time}-${event.event}`} className={isUntrusted(event.event) ? "is-untrusted" : ""}>
              <time>{new Date(event.time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
              <span className="tag">{event.service}</span>
              <span className="timeline-event">{event.event}</span>
              {isUntrusted(event.event) && <UntrustedTag />}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function formatTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function IncidentOverview({ incident, busy, onRunTriage, hasPlan }) {
  const sources = [
    { label: "Metrics", count: incident.metrics?.length ?? 0 },
    { label: "Logs", count: incident.logs?.length ?? 0 },
    { label: "Traces", count: incident.traces?.length ?? 0 },
  ];
  const missing = sources.filter((source) => source.count === 0);

  return (
    <section className="card overview">
      <p className="section-label">{hasPlan ? "Diagnosis not loaded" : "Before triage"}</p>
      {hasPlan && (
        <p className="missing-note">
          A plan from an earlier run is saved, but its diagnosis isn&apos;t. Run triage again to see the
          evidence.
        </p>
      )}
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

export default function DiagnosisPanel({ report, busy, incident, onRunTriage, hasPlan }) {
  const [showAlternatives, setShowAlternatives] = useState(false);

  if (busy) {
    return <TriageProgress incidentId={incident?.incident_id} />;
  }

  if (!report && incident) {
    return <IncidentOverview incident={incident} busy={busy} onRunTriage={onRunTriage} hasPlan={hasPlan} />;
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
            <HypothesisCard hypothesis={leading} leading incident={incident} />
            <HypothesisCard hypothesis={alternatives[0]} incident={incident} />
          </div>
        ) : (
          <HypothesisCard hypothesis={leading} leading incident={incident} />
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
              .map((hypothesis) => (
                <HypothesisCard key={hypothesis.id} hypothesis={hypothesis} incident={incident} />
              ))}
        </div>
      )}

      <Timeline events={report.timeline} />

      {report.unknowns?.length > 0 && (
        <div className="note note-warn">
          <span className="section-label">Unknowns</span>
          <ul>
            {report.unknowns.map((unknown) => (
              <li key={unknown} className={isUntrusted(unknown) ? "is-untrusted" : ""}>
                {unknown} {isUntrusted(unknown) && <UntrustedTag />}
              </li>
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
