const DIAGNOSIS_COPY = {
  ok: {
    tone: "good",
    title: "Diagnosis OK",
    detail: "Evidence was verified against the recorded telemetry.",
  },
  uncertain: {
    tone: "warn",
    title: "Uncertain diagnosis",
    detail: "Top hypotheses are close or confidence is low. Compare H1 and H2 before approving.",
  },
  insufficient_evidence: {
    tone: "danger",
    title: "Insufficient evidence. Manual review needed",
    detail: "No hypothesis survived the evidence check.",
  },
  failed: {
    tone: "danger",
    title: "Diagnosis failed",
    detail: "The report did not match this incident. Triage the raw packet manually.",
  },
};

export function diagnosisCopy(status) {
  return DIAGNOSIS_COPY[status] || {
    tone: "neutral",
    title: "Not validated",
    detail: "This report has not been checked by the orchestrator.",
  };
}

export default function StatusBanner({ status, tone, message }) {
  const copy = status ? diagnosisCopy(status) : { tone: tone || "neutral", title: message };
  return (
    <div className={`banner banner-${copy.tone}`} role={copy.tone === "danger" ? "alert" : "status"}>
      <span className="banner-icon" aria-hidden="true">
        {copy.tone === "good" ? "✓" : "!"}
      </span>
      <div>
        <strong>{copy.title}</strong>
        {copy.detail && <p>{copy.detail}</p>}
      </div>
    </div>
  );
}
