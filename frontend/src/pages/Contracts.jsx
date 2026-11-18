import { useEffect, useState } from "react";
import { api, inr } from "../api.js";
import { ErrorNote } from "../components/Dialog.jsx";
import ContractForm from "../components/ContractForm.jsx";

// B6: every contract (register, PDF-only, added by a buyer), and adding one from its PDF or by hand.
export default function Contracts() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(null);
  const load = () => api("/api/contracts").then(setRows, setError);
  useEffect(() => { load(); }, []);
  return (
    <main>
      <h1>Contracts</h1>
      <AddContract onSaved={(c) => { setSaved(c); load(); }} />
      {saved && <p className="notice" role="status">Saved {saved.contract_id} ({saved.source}, nothing consumed). It applies
        to every run made from now on.{saved.warnings?.map((w) => <span key={w} className="warn"> {w}</span>)}</p>}
      <ErrorNote error={error} />
      {rows && rows.length === 0 && <p className="muted">No contracts.</p>}
      {rows && rows.length > 0 && (
        <table>
          <thead><tr><th>Contract</th><th>Supplier</th><th>Valid</th><th>Ceiling</th><th>Consumed</th><th>Items</th><th>Source</th></tr></thead>
          <tbody>{rows.map((c) => (
            <tr key={c.contract_id}>
              <td className="nowrap">{c.contract_id}</td>
              <td>{c.supplier_id} {c.supplier_name}{c.supplier_status !== "Active" && <> <span className="badge bad">{c.supplier_status}</span></>}</td>
              <td className="nowrap">{c.start_date} to {c.end_date}</td>
              <td>{inr(c.value_cap)}</td>
              <td>{inr(c.consumed_value)}{c.consumed_as_of ? <span className="muted"> at {c.consumed_as_of}</span> : null}</td>
              <td>{c.lines.map((l) => l.item_code).join(", ")}</td>
              <td>{c.source}{c.added_by !== "seed" && <span className="muted"> by {c.added_by}</span>}</td>
            </tr>))}</tbody>
        </table>
      )}
    </main>
  );
}

function AddContract({ onSaved }) {
  const [file, setFile] = useState(null);
  const [read, setRead] = useState(null); // {form} or {error, llm_available}
  const [manual, setManual] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function readPdf(useLlm) {
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("file", file);
    try {
      setRead(await api(`/api/contracts/read-pdf${useLlm ? "?llm=1" : ""}`, { method: "POST", form }));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  function reset() { setRead(null); setManual(false); setFile(null); setError(null); }

  if (read?.form || manual) {
    return (
      <section className="card selected" aria-label="Add a contract">
        <h2>Add a contract</h2>
        {read?.form && (read.form.needs_checking
          ? <p className="warn">Drafted by the {read.form.read_by}. Check every field against the PDF before saving.</p>
          : <p className="notice">Read from the PDF by the deterministic reader. Check it and save.</p>)}
        <ContractForm initial={read?.form} source={read?.form ? "pdf" : "manual"} sourceFile={file?.name}
          onSaved={(c) => { reset(); onSaved(c); }} onCancel={reset} />
      </section>
    );
  }
  return (
    <form className="card" aria-label="Add a contract" onSubmit={(e) => { e.preventDefault(); if (file && !busy) readPdf(false); }}>
      <h2>Add a contract</h2>
      <label>Signed contract PDF <input type="file" accept=".pdf,application/pdf"
        onChange={(e) => { setFile(e.target.files[0] || null); setRead(null); }} /></label>
      <div className="actions">
        <button type="submit" className="primary" disabled={!file || busy}>{busy ? "Reading..." : "Read the PDF"}</button>
        <button type="button" onClick={() => setManual(true)}>Fill in by hand</button>
      </div>
      {read?.error && (
        <div className="error" role="alert">
          <p>The reader could not read this file: {read.error}</p>
          <div className="actions">
            {read.llm_available && <button type="button" disabled={busy} onClick={() => readPdf(true)}>Ask the AI to read it (you check it)</button>}
            <button type="button" onClick={() => setManual(true)}>Fill in by hand</button>
          </div>
        </div>
      )}
      <ErrorNote error={error} />
    </form>
  );
}
