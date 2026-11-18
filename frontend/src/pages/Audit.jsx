import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { ErrorNote } from "../components/Dialog.jsx";

// B9: the audit log, read-only, newest first, filterable by who and by action.
export default function Audit() {
  const [data, setData] = useState(null);
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    const q = new URLSearchParams();
    if (actor) q.set("actor", actor);
    if (action) q.set("action", action);
    api(`/api/audit${q.toString() ? `?${q}` : ""}`).then(setData, setError);
  }, [actor, action]);
  useEffect(() => { load(); }, [load]);

  return (
    <main>
      <h1>Audit log</h1>
      <ErrorNote error={error} />
      {data && (
        <>
          <div className="filters">
            <label>Who <select value={actor} onChange={(e) => setActor(e.target.value)}>
              <option value="">Everyone</option>{data.actors.map((a) => <option key={a}>{a}</option>)}</select></label>
            <label>Action <select value={action} onChange={(e) => setAction(e.target.value)}>
              <option value="">All actions</option>{data.actions.map((a) => <option key={a}>{a}</option>)}</select></label>
            <span className="muted">{data.entries.length} entries, newest first. Entries cannot be changed or deleted.</span>
          </div>
          {data.entries.length === 0 ? <p className="muted">Nothing recorded yet.</p> : (
            <table>
              <thead><tr><th>When (UTC)</th><th>Who</th><th>Action</th><th>On</th><th>Comment</th></tr></thead>
              <tbody>{data.entries.map((e) => (
                <tr key={e.id}><td className="nowrap">{String(e.at).slice(0, 19).replace("T", " ")}</td>
                  <td>{e.actor}{e.role && <span className="muted"> ({e.role})</span>}</td><td>{e.action}</td>
                  <td>{e.entity_type} {e.entity_id}</td><td>{e.comment}</td></tr>))}</tbody>
            </table>
          )}
        </>
      )}
    </main>
  );
}
