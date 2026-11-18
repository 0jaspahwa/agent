import { useState } from "react";
import { api } from "../api.js";
import { ErrorNote } from "../components/Dialog.jsx";
import { KIT_LOADED_EVENT } from "../components/KitBanner.jsx";

// Load kit data (Procurement): the task kit is not in the repo, so after deploying it is uploaded here once.
// The server finds every file by name; loading the same kit again changes nothing.
export default function KitData() {
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    if (!files.length) return;
    const form = new FormData();
    for (const f of files) form.append("files", f, f.name);
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api("/api/admin/load-kit", { method: "POST", form }));
      window.dispatchEvent(new Event(KIT_LOADED_EVENT));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>Load kit data</h1>
      <p className="muted">
        The task kit is not in the repo. Upload the kit zip exactly as distributed, a zip of its folders, or the six
        CSV files and the contract PDFs. Items, suppliers, plants, PO history, the contract register and every
        contract PDF are read; the sample PR batch is not (process it under Batches). Uploading the same kit again
        changes nothing.
      </p>
      <form onSubmit={submit} className="card">
        <label>Kit zip or files{" "}
          <input type="file" multiple accept=".zip,.csv,.pdf" aria-label="Kit zip or files"
            onChange={(e) => setFiles(Array.from(e.target.files || []))} />
        </label>{" "}
        <button type="submit" className="primary" disabled={!files.length || busy}>
          {busy ? "Reading the kit..." : "Load kit data"}
        </button>
      </form>
      <ErrorNote error={error} />
      {result && (
        <section>
          <p className="notice"><b>{result.message}</b></p>
          <table>
            <thead><tr><th>Table</th><th>Rows in the kit</th><th>Added now</th></tr></thead>
            <tbody>{Object.entries(result.tables).map(([name, t]) => (
              <tr key={name}><td>{name}</td><td>{t.in_kit}</td><td>{t.added}</td></tr>))}</tbody>
          </table>
          <p>Contract PDFs read: {result.contract_pdfs.join(", ")}</p>
          {result.ignored.length > 0 && (
            <>
              <p className="muted">Not loaded:</p>
              <ul className="muted">{result.ignored.map((i) => <li key={i}>{i}</li>)}</ul>
            </>
          )}
        </section>
      )}
    </main>
  );
}
