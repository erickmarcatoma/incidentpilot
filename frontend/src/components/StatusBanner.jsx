export default function StatusBanner({ tone = "info", message }) {
  return (
    <div className={`status-banner status-banner-${tone}`} role="alert">
      <span aria-hidden="true">{tone === "error" ? "!" : "i"}</span>
      <p>{message}</p>
    </div>
  );
}