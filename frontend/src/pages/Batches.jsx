import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { ErrorNote } from "../components/Dialog.jsx";

const MODE_WORDS = { by_requirement_date: "version by requirement date", named_version: "one named version" };

// B5: process a PR batch CSV. Choose the policy (by requirement date, or one named approved version), see the
// result by route, download the decisions CSV, open the run in the workspace.
export default function Batches() {
  const [runs, setRuns] = useState(null);
  const [versions, setVersions] = useState([]);
  const [file, setFile] = useState(null);
  const [version, setVersion] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function load() {
    try {
      const [r, p] = await Promise.all([api("/api/runs"), api("/api/policies")]);
      setRuns(r);
      setVersions(p.filter((v) => v.status === "approved"));
    } catch (e) {
      setError(e);
    }
  }
  useEffect(() => { load(); }, []);

  async function submit(e) {
    e.preventDefault();
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("file", file);
    if (version) form.append("policy_version", version);
    try {
      setResult(await api("/api/process-batch", { method: "POST", form }));
      load();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>Batches</h1>
      <form className="card" onSubmit={submit}>
        <h2>Process a PR batch</h2>
        <label>CSV file in the sample batch format
          <input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files[0] || null)} /></label>
        <label>Policy <select value={version} onChange={(e) => setVersion(e.target.value)}>
          <option value="">The version in force on each requirement date</option>
          {versions.map((v) => <option key={v.id} value={v.version}>Only version {v.version} (effective {v.effective_from}), for every requirement</option>)}
        </select></label>
        <div className="actions">
          <button type="submit" className="primary" disabled={!file || busy}>{busy ? "Processing..." : "Process"}</button>
          <span className="muted">Run 1 on Thursday: choose version 5.0. Run 2: after approving the amendment, the version by date.</span>
        </div>
        <ErrorNote error={error} />
      </form>

      {result && (
        <section className="card selected" aria-label="Result">
          <h2>Run {result.run_id}: {result.filename}</h2>
          <p>{result.lines} lines, {result.requirements} requirements, {result.purchase_orders} purchase orders,
            processed in {result.processing_seconds} s; policy: {MODE_WORDS[result.policy_mode.mode]}
            {result.policy_mode.version && ` ${result.policy_mode.version}`}.</p>
          <RouteTable counts={result.summary_by_route} />
          <div className="actions">
            <a className="button primary" href={result.export_url}>Download the decisions CSV</a>
            <Link to={`/workspace?run=${result.run_id}`}>Open in the workspace</Link>
          </div>
        </section>
      )}

      <h2>Earlier runs</h2>
      {runs && runs.length === 0 && <p className="muted">No runs yet.</p>}
      {runs && runs.length > 0 && (
        <table>
          <thead><tr><th>Run</th><th>Source</th><th>Lines</th><th>Policy</th><th>Started</th><th></th></tr></thead>
          <tbody>{runs.map((r) => (
            <tr key={r.run_id}>
              <td>{r.run_id}</td><td>{r.kind === "batch" ? r.filename : "chat requests"}</td><td>{r.lines ?? "-"}</td>
              <td>{MODE_WORDS[r.policy_mode?.mode] || "-"}{r.policy_mode?.version ? ` ${r.policy_mode.version}` : ""}</td>
              <td>{String(r.started_at).slice(0, 16).replace("T", " ")} by {r.started_by}</td>
              <td className="nowrap"><a href={`/api/runs/${r.run_id}/export.csv`}>CSV</a> · <Link to={`/workspace?run=${r.run_id}`}>Workspace</Link></td>
            </tr>))}</tbody>
        </table>
      )}
    </main>
  );
}

function RouteTable({ counts }) {
  return (
    <table>
      <thead><tr><th>Route</th><th>Lines</th></tr></thead>
      <tbody>{Object.entries(counts).map(([route, n]) => <tr key={route}><td>{route}</td><td>{n}</td></tr>)}</tbody>
    </table>
  );
}
