import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { ErrorNote } from "../components/Dialog.jsx";

const STATUS_BADGE = { approved: "good", draft: "warn", withdrawn: "bad", discarded: "" };

// B7: policy versions, and starting a change: from an amendment document or a description (the AI drafts it in
// the background), or from the current version with no AI at all.
export default function Policies() {
  const [rows, setRows] = useState(null);
  const [file, setFile] = useState(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const navigate = useNavigate();
  useEffect(() => { api("/api/policies").then(setRows, setError); }, []);

  async function start(body) {
    setBusy(true);
    setError(null);
    try {
      const draft = await api("/api/policies/drafts", { method: "POST", ...body });
      navigate(`/policies/${draft.id}`);
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  }
  function submit(e) {
    e.preventDefault();
    if (busy || (!file && !text.trim())) return;
    if (file) {
      const form = new FormData();
      form.append("file", file);
      start({ form });
    } else start({ body: { text } });
  }

  return (
    <main>
      <h1>Policy</h1>
      <form className="card" onSubmit={submit}>
        <h2>Change the policy</h2>
        <p>Upload the amendment, or describe the change. The AI drafts a new version; you review what changes and its
          impact, and approve it. Nothing changes until it is approved.</p>
        <label>Amendment document (PDF, DOCX, TXT or MD)
          <input type="file" accept=".pdf,.docx,.txt,.md" onChange={(e) => setFile(e.target.files[0] || null)} /></label>
        <label>or describe it <textarea rows="4" value={text} onChange={(e) => setText(e.target.value)}
          placeholder="From 1 Dec 2026 the spot PO limit is at or below Rs 1,50,000." /></label>
        <div className="actions">
          <button type="submit" className="primary" disabled={busy || (!file && !text.trim())}>{busy ? "Starting..." : "Draft with AI"}</button>
          <button type="button" disabled={busy} onClick={() => start({ body: { from_current: true } })}>
            Edit the current version by hand (no AI)</button>
        </div>
        <ErrorNote error={error} />
      </form>
      <h2>Versions</h2>
      {rows && (
        <table>
          <thead><tr><th>Version</th><th>Status</th><th>Effective from</th><th>Change</th><th>By</th></tr></thead>
          <tbody>{[...rows].reverse().map((v) => (
            <tr key={v.id}>
              <td><Link to={`/policies/${v.id}`}>{v.version}</Link></td>
              <td><span className={`badge ${STATUS_BADGE[v.status] || ""}`}>{v.status}</span>
                {v.status === "draft" && v.drafting_status !== "ready" && <span className="muted"> ({v.drafting_status === "drafting" ? "AI drafting..." : "drafting failed"})</span>}</td>
              <td>{v.effective_from || <span className="muted">not set</span>}</td>
              <td>{v.change_summary}</td>
              <td>{v.approved_by || v.drafted_by}</td>
            </tr>))}</tbody>
        </table>
      )}
    </main>
  );
}
