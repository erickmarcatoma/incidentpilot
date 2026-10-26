function formatDate(value) {
  return new Date(value).toLocaleString();
}

export default function DiagnosisPanel({ report }) {
  if (!report) {
    return (
      <section className="panel diagnosis-panel diagnosis-empty">
        <p className="eyebrow">DIAGNOSIS</p>
        <h2>Root-cause report</h2>
        <p className="empty-state">
          Run triage on a recorded incident to inspect evidence-backed hypotheses.
        </p>
      </section>
    );
  }

  return (
    <section className="panel diagnosis-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">DIAGNOSIS / {report.incident_id}</p>
          <h2>Root-cause report</h2>
        </div>
        <span className={`status-pill status-${report.status || "pending"}`}>
          {(report.status || "unvalidated").replaceAll("_", " ")}
        </span>
      </div>
      <div className="report-summary">
        <div>
          <span className="field-label">Affected services</span>
          <p>{report.affected_services.join(", ")}</p>
        </div>
        <div>
          <span className="field-label">Incident window</span>
          <p>
            {formatDate(report.window.start)} – {formatDate(report.window.end)}
          </p>
        </div>
      </div>
      <div className="hypothesis-list">
        {report.hypotheses.map((hypothesis, index) => (
          <article className="hypothesis-card" key={hypothesis.id}>
            <div className="hypothesis-heading">
              <span className="hypothesis-id">{hypothesis.id}</span>
              <span className="confidence">
                {Math.round(hypothesis.confidence * 100)}% confidence
              </span>
              {index === 0 && <span className="top-hypothesis">Leading</span>}
            </div>
            <h3>{hypothesis.cause}</h3>
            <p className="hypothesis-meta">
              {hypothesis.category.replaceAll("_", " ")} · {hypothesis.service}
            </p>
            <div className="evidence-list">
              {hypothesis.evidence.map((evidence) => (
                <blockquote key={`${evidence.source}-${evidence.ref}`}>
                  <span>
                    {evidence.source} / {evidence.ref}
                  </span>
                  “{evidence.quote}”
                </blockquote>
              ))}
            </div>
          </article>
        ))}
      </div>
      {report.unknowns?.length > 0 && (
        <div className="unknowns">
          <span className="field-label">Unknowns</span>
          <ul>
            {report.unknowns.map((unknown) => (
              <li key={unknown}>{unknown}</li>
            ))}
          </ul>
        </div>
      )}
      {report.validation_notes?.length > 0 && (
        <div className="validation-notes">
          {report.validation_notes.map((note) => (
            <p key={note}>{note}</p>
          ))}
        </div>
      )}
    </section>
  );
}