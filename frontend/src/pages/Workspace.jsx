import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, inr } from "../api.js";
import { ErrorNote } from "../components/Dialog.jsx";
import RequirementDetail from "../components/RequirementDetail.jsx";

// B4: the buyer workspace. Choose a run (the latest batch run by default, or the open chat requests); the queue
// on the left, filtered; the selected requirement on the right with one primary action, Approve.
export default function Workspace() {
  const [runs, setRuns] = useState([]);
  const [params] = useSearchParams();
  const [choice, setChoice] = useState(params.get("run") || ""); // "" = latest batch run; "chat"; or a run id
  const [view, setView] = useState(null);
  const [selected, setSelected] = useState(null);
  const [tab, setTab] = useState("requirements");
  const [filters, setFilters] = useState({ needsAction: true, route: "", plant: "", flag: "" });
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const load = useCallback(async () => {
    try {
      const query = choice === "chat" ? "?kind=chat" : choice ? `?run_id=${choice}` : "";
      const [list, data] = await Promise.all([api("/api/workspace/runs"), api(`/api/workspace${query}`)]);
      setRuns(list);
      setView(data);
      setError(null);
    } catch (e) {
      setError(e);
    }
  }, [choice]);
  useEffect(() => { load(); }, [load]);

  const shown = useMemo(() => (view?.requirements || []).filter((r) =>
    (!filters.needsAction || r.status === "open") && (!filters.route || r.route === filters.route)
    && (!filters.plant || r.plant === filters.plant)
    && (!filters.flag || (filters.flag === "any" ? r.flags.length > 0 : r.flags.some((f) => f.code === filters.flag)))),
  [view, filters]);
  const current = view?.requirements.find((r) => r.id === selected) || null;
  const flagCodes = [...new Set((view?.requirements || []).flatMap((r) => r.flags.map((f) => f.code)))].sort();

  async function acted(message, conflict) {
    setNotice(message);
    await load();
    if (conflict) setError(null);
  }

  if (!view) return <main><h1>Workspace</h1><ErrorNote error={error} />{!error && <p>Loading...</p>}</main>;
  const set = (k) => (e) => setFilters({ ...filters, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  return (
    <main>
      <h1>Workspace</h1>
      <div className="filters">
        <label>Run <select value={choice} onChange={(e) => { setChoice(e.target.value); setSelected(null); }}>
          <option value="">Latest batch run</option>
          <option value="chat">Open chat requests</option>
          {runs.map((r) => <option key={r.id} value={r.id}>{r.label} · {r.open} of {r.requirements} need action</option>)}
        </select></label>
      </div>
      {!view.run ? (
        <p className="notice">{choice === "chat" ? "No chat requests yet." : "No batch has been processed yet. Upload one under Batches."}</p>
      ) : (
        <>
          <p className="muted">{view.run.label}: {view.run.open} of {view.run.requirements} requirements need action.</p>
          <div className="tabs" role="tablist">
            <button type="button" role="tab" className={tab === "requirements" ? "on" : ""} onClick={() => setTab("requirements")}>
              Requirements ({view.requirements.length})</button>
            <button type="button" role="tab" className={tab === "np" ? "on" : ""} onClick={() => setTab("np")}>
              Not processed ({view.not_processed.length})</button>
          </div>
          {notice && <p className="notice" role="status">{notice}</p>}
          <ErrorNote error={error} />
          {tab === "np" ? <NotProcessed rows={view.not_processed} /> : (
            <div className="grid2">
              <section aria-label="Queue">
                <div className="filters">
                  <label className="choice"><input type="checkbox" checked={filters.needsAction} onChange={set("needsAction")} /> Needs action</label>
                  <label>Route <select value={filters.route} onChange={set("route")}><option value="">All</option>
                    {view.routes.map((r) => <option key={r}>{r}</option>)}</select></label>
                  <label>Plant <select value={filters.plant} onChange={set("plant")}><option value="">All</option>
                    {view.plants.map((p) => <option key={p}>{p}</option>)}</select></label>
                  <label>Flags <select value={filters.flag} onChange={set("flag")}><option value="">All</option>
                    <option value="any">Any flag</option>{flagCodes.map((f) => <option key={f}>{f}</option>)}</select></label>
                </div>
                {shown.length === 0 ? <p className="muted">Nothing matches these filters.</p> : (
                  <table>
                    <thead><tr><th>Req</th><th>Item</th><th>Plant</th><th>Route</th><th>Value</th><th>Status</th></tr></thead>
                    <tbody>
                      {shown.map((r) => (
                        <tr key={r.id} onClick={() => { setSelected(r.id); setNotice(null); }}
                          className={r.id === selected ? "selected-row" : ""} style={{ cursor: "pointer" }}>
                          <td className="nowrap"><button type="button" className="link" onClick={() => setSelected(r.id)}>{r.group_id}</button></td>
                          <td>{r.item_description}{r.flags.length > 0 && <> <span className="badge warn">{[...new Set(r.flags.map((f) => f.code))].join(" ")}</span></>}</td>
                          <td>{r.plant}</td><td>{r.route_words}</td><td>{inr(r.value_inr)}</td>
                          <td><span className={`badge ${r.status === "open" ? "" : "good"}`}>{r.status}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>
              <section aria-label="Requirement">
                {current ? <RequirementDetail req={current} all={view.requirements} onDone={acted}
                  onConflict={(e) => { setError(e); load(); }} />
                  : <p className="muted">Choose a requirement on the left to see why it was decided and act on it.</p>}
              </section>
            </div>
          )}
        </>
      )}
    </main>
  );
}

function NotProcessed({ rows }) {
  if (rows.length === 0) return <p className="muted">Every line in this run could be processed.</p>;
  return (
    <table>
      <thead><tr><th>PR</th><th>Line</th><th>Description</th><th>Plant</th><th>Quantity</th><th>Why it was not processed</th></tr></thead>
      <tbody>{rows.map((r) => (
        <tr key={`${r.pr_no}/${r.pr_line}`}><td>{r.pr_no}</td><td>{r.pr_line}</td><td>{r.description}</td><td>{r.plant}</td>
          <td>{r.quantity}</td><td>{r.reason}</td></tr>))}</tbody>
    </table>
  );
}
