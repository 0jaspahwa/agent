import { useEffect, useState } from "react";
import { api } from "../api.js";
import { ErrorNote } from "./Dialog.jsx";

// What a draft would change on a stored batch: route counts before and after, and every line that changes.
// For an approved version, the preview stored at approval (`stored`).
export default function ImpactPreview({ versionId, stored }) {
  const [batches, setBatches] = useState([]);
  const [batch, setBatch] = useState("");
  const [result, setResult] = useState(stored || null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => {
    if (stored) return;
    api("/api/runs").then((runs) => {
      const seen = runs.filter((r) => r.kind === "batch" && r.batch_id)
        .filter((r, i, all) => all.findIndex((x) => x.batch_id === r.batch_id) === i);
      setBatches(seen);
      if (seen.length) setBatch(String(seen[0].batch_id));
    }, setError);
  }, [stored]);

  async function preview(e) {
    e.preventDefault();
    setBusy(true);
    try {
      setResult(await api(`/api/policies/drafts/${versionId}/preview?batch_id=${batch}`, { method: "POST" }));
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-label="Impact">
      <h2>{stored ? "Impact recorded at approval" : "Impact preview"}</h2>
      {!stored && (batches.length === 0 ? <p className="muted">No batch has been processed yet, so there is nothing to preview.</p> : (
        <form className="filters" onSubmit={preview}>
          <label>Batch <select value={batch} onChange={(e) => setBatch(e.target.value)}>
            {batches.map((r) => <option key={r.batch_id} value={r.batch_id}>{r.filename} (run {r.run_id}, {r.lines} lines)</option>)}
          </select></label>
          <button type="submit" disabled={busy}>{busy ? "Previewing..." : "Preview the impact"}</button>
        </form>
      ))}
      <ErrorNote error={error} />
      {result && result.batch_id != null && (
        <>
          <p><b>{result.explanation}</b> ({result.lines_under_draft} lines fall under the new version; requirements
            {" "}{(result.batch_dates || []).join(" to ")}).</p>
          <table>
            <thead><tr><th>Route</th><th>Before</th><th>After</th></tr></thead>
            <tbody>{[...new Set([...Object.keys(result.routes_before), ...Object.keys(result.routes_after)])].sort().map((r) => (
              <tr key={r}><td>{r}</td><td>{result.routes_before[r] || 0}</td><td>{result.routes_after[r] || 0}</td></tr>))}</tbody>
          </table>
          {result.changes.length > 0 && (
            <table>
              <thead><tr><th>Line</th><th>Rule</th><th>What changes</th></tr></thead>
              <tbody>{result.changes.slice(0, 300).map((c) => (
                <tr key={c.line}><td className="nowrap">{c.line}</td><td>{c.rule_before} → {c.rule_after}</td>
                  <td>{Object.entries(c.changes).map(([k, x]) => <div key={k}>{k}: {String(x.before || "-")} → {String(x.after || "-")}</div>)}</td></tr>))}</tbody>
            </table>
          )}
        </>
      )}
      {result && result.batch_id == null && <p>{result.explanation}</p>}
    </section>
  );
}
