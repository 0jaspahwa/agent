import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api.js";
import { Confirm, ErrorNote } from "../components/Dialog.jsx";
import ImpactPreview from "../components/ImpactPreview.jsx";

// B7: one policy version. While the AI drafts, the page checks every few seconds. A ready draft shows, in this
// order: what the AI could not express (so nothing is narrowed silently), what changes in plain words, anything
// that must be fixed, the impact on a batch, and the JSON to edit; then Approve.
export default function PolicyDetail({ pollMs = 3000 }) {
  const { id } = useParams();
  const [v, setV] = useState(null);
  const [error, setError] = useState(null);
  const [dialog, setDialog] = useState(null);
  const navigate = useNavigate();
  const load = useCallback(() => api(`/api/policies/${id}`).then((x) => { setV(x); setError(null); }, setError), [id]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (v?.drafting_status !== "drafting") return undefined;
    const t = setTimeout(load, pollMs);
    return () => clearTimeout(t);
  }, [v, load, pollMs]);

  async function act(path, body) {
    try {
      await api(path, { method: "POST", body });
      setDialog(null);
      await load();
    } catch (e) {
      setDialog(null);
      setError(e);
    }
  }
  async function manual() {
    try {
      const d = await api("/api/policies/drafts", { method: "POST", body: { from_current: true } });
      navigate(`/policies/${d.id}`);
    } catch (e) {
      setError(e);
    }
  }

  if (!v) return <main><ErrorNote error={error} />{!error && <p>Loading...</p>}</main>;
  const draft = v.status === "draft";
  const by = v.drafted_by.startsWith("llm:") && v.drafting_seconds != null
    ? `drafted by ${v.drafted_by.slice(4)} in ${Math.round(v.drafting_seconds)} s (${v.draft_mode || "operations"})` : `drafted by ${v.drafted_by}`;

  if (draft && v.drafting_status === "drafting") {
    return (
      <main>
        <h1>Drafting version {v.version}</h1>
        <p className="notice" role="status">The AI is drafting this amendment. This page checks again every few seconds; it
          usually takes under a minute, and after 5 minutes it is marked failed.</p>
        <p>You do not have to wait: <button type="button" onClick={manual}>edit the current version by hand instead</button></p>
      </main>
    );
  }
  if (draft && v.drafting_status === "failed") {
    return (
      <main>
        <h1>Drafting failed for version {v.version}</h1>
        <p className="error" role="alert">{v.drafting_error}</p>
        <div className="actions">
          <button type="button" className="primary" onClick={manual}>Edit the current version by hand</button>
          <button type="button" onClick={() => setDialog("discard")}>Discard this draft</button>
        </div>
        {dialog === "discard" && <Confirm title="Discard this draft?" confirmLabel="Discard" onClose={() => setDialog(null)}
          onConfirm={() => act(`/api/policies/drafts/${v.id}/discard`, { comment: "drafting failed" })}><p>It stays on record as discarded.</p></Confirm>}
      </main>
    );
  }

  return (
    <main>
      <p><Link to="/policies">All versions</Link></p>
      <h1>Policy version {v.version} <span className="badge">{v.status}</span></h1>
      <p>Effective from <b>{v.effective_from || "NOT SET"}</b> · based on {v.base_version || "-"} · {by}
        {v.approved_by && <> · approved by {v.approved_by} at {String(v.approved_at).slice(0, 16).replace("T", " ")}</>}
        {v.closed_by && <> · {v.status} by {v.closed_by}: {v.close_comment}</>}</p>
      <ErrorNote error={error} />

      {draft && (
        <div className="actions">
          <button type="button" className="primary" disabled={v.errors.length > 0} onClick={() => setDialog("approve")}>Approve</button>
          <button type="button" onClick={() => setDialog("discard")}>Discard</button>
          {v.errors.length > 0 && <span className="warn">Fix the problems below before approving.</span>}
        </div>
      )}
      {v.status === "approved" && v.base_version && (
        <div className="actions"><button type="button" onClick={() => setDialog("withdraw")}>Withdraw this version</button></div>
      )}

      {(v.not_expressed.length > 0 || draft) && (
        <section className={v.not_expressed.length ? "error" : "notice"} aria-label="Not expressed">
          <h2>What the AI could not express</h2>
          {v.not_expressed.length ? <ul>{v.not_expressed.map((x) => <li key={x}>{x}</li>)}</ul>
            : <p>Nothing reported: every part of the amendment was expressed. Still check the changes below.</p>}
        </section>
      )}
      <h2>What changes</h2>
      {v.diff.length ? <ul>{v.diff.map((x) => <li key={x}>{x}</li>)}</ul> : <p className="muted">Nothing differs from the base version.</p>}
      {v.errors.length > 0 && <><h2 className="warn">Must be fixed before approval</h2><ul>{v.errors.map((x) => <li key={x}>{x}</li>)}</ul></>}
      {v.warnings.length > 0 && <><h3>Warnings</h3><ul>{v.warnings.map((x) => <li key={x}>{x}</li>)}</ul></>}
      {v.translation_notes.length > 0 && <><h3>Translation notes</h3><ul>{v.translation_notes.map((x) => <li key={x}>{x}</li>)}</ul></>}

      {draft && v.errors.length === 0 && <ImpactPreview versionId={v.id} />}
      {!draft && v.impact_summary && <ImpactPreview stored={v.impact_summary} />}
      {draft && <JsonEditor v={v} onSaved={load} />}
      {v.source_document_text && (
        <details><summary>Amendment text ({v.source_document_name})</summary><pre className="json">{v.source_document_text}</pre></details>)}
      {!draft && <details><summary>Policy document (JSON)</summary><pre className="json">{JSON.stringify(v.document, null, 2)}</pre></details>}

      {dialog === "approve" && (
        <Confirm title={`Approve version ${v.version}?`} confirmLabel="Approve" onClose={() => setDialog(null)}
          onConfirm={() => act(`/api/policies/drafts/${v.id}/approve`, {})}>
          <p>Version {v.version} applies to every requirement dated from {v.effective_from}. An approved version cannot be
            edited; it can only be withdrawn. The impact on the latest batch is stored with the approval.</p>
        </Confirm>
      )}
      {dialog === "discard" && (
        <Confirm title={`Discard draft ${v.version}?`} confirmLabel="Discard" onClose={() => setDialog(null)}
          onConfirm={() => act(`/api/policies/drafts/${v.id}/discard`, { comment: "discarded on review" })}>
          <p>It stays on record as discarded and can no longer be approved.</p>
        </Confirm>
      )}
      {dialog === "withdraw" && <WithdrawDialog v={v} onClose={() => setDialog(null)}
        onConfirm={(comment) => act(`/api/policies/${v.id}/withdraw`, { comment })} />}
    </main>
  );
}

function WithdrawDialog({ v, onClose, onConfirm }) {
  const [comment, setComment] = useState("");
  return (
    <Confirm title={`Withdraw version ${v.version}?`} confirmLabel="Withdraw" onClose={onClose}
      onConfirm={() => comment.trim() && onConfirm(comment.trim())}>
      <p>Later runs stop using it; runs already made keep their record.</p>
      <label>Why (required) <input value={comment} onChange={(e) => setComment(e.target.value)} /></label>
    </Confirm>
  );
}

function JsonEditor({ v, onSaved }) {
  const [text, setText] = useState(() => JSON.stringify(v.document, null, 2));
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function save(e) {
    e.preventDefault();
    let doc;
    try {
      doc = JSON.parse(text);
    } catch (err) {
      setError(`The JSON could not be read: ${err.message}. Nothing was saved.`);
      return;
    }
    setBusy(true);
    try {
      await api(`/api/policies/drafts/${v.id}`, { method: "PUT", body: doc });
      setError(null);
      onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="card" onSubmit={save}>
      <h2>Edit the draft (JSON)</h2>
      <p className="muted">Set the effective date, fix a rule, or make the whole change here. Saving re-checks it and
        updates the changes above.</p>
      <textarea aria-label="Policy JSON" rows="18" style={{ width: "100%", fontFamily: "monospace" }} value={text}
        onChange={(e) => setText(e.target.value)} />
      <ErrorNote error={error} />
      <div className="actions"><button type="submit" disabled={busy}>{busy ? "Saving..." : "Save and re-check"}</button></div>
    </form>
  );
}
