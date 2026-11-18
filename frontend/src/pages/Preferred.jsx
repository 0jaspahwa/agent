import { useEffect, useState } from "react";
import { api, inr } from "../api.js";
import { ErrorNote } from "../components/Dialog.jsx";

const today = () => new Date().toISOString().slice(0, 10);

// B8: the preferred supplier list for an item on a date, with every score broken into its parts, and the CSV
// export (top 3 per item) for that date.
export default function Preferred() {
  const [items, setItems] = useState([]);
  const [item, setItem] = useState("");
  const [asOf, setAsOf] = useState(today());
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { api("/api/items").then(setItems, setError); }, []);

  async function show(e) {
    e.preventDefault();
    if (!item) return;
    try {
      setResult(await api(`/api/preferred-suppliers?item_code=${encodeURIComponent(item)}&as_of=${asOf}`));
      setError(null);
    } catch (err) {
      setError(err);
      setResult(null);
    }
  }

  return (
    <main>
      <h1>Preferred suppliers</h1>
      <form className="filters" onSubmit={show}>
        <label>Item <select value={item} onChange={(e) => setItem(e.target.value)}>
          <option value="">Choose an item</option>
          {items.map((i) => <option key={i.item_code} value={i.item_code}>{i.item_code} {i.description}</option>)}
        </select></label>
        <label>As of <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></label>
        <button type="submit" className="primary" disabled={!item}>Show the list</button>
        <a href={`/api/preferred-suppliers/export.csv?as_of=${asOf}`}>Download the CSV for {asOf} (top 3, every item)</a>
      </form>
      <ErrorNote error={error} />
      {result && (
        <section aria-label="Preferred list">
          <h2>{result.item.item_code} {result.item.description} <span className="muted">· {result.item.category} · as of {result.as_of} · policy v{result.policy_version}</span></h2>
          {result.preferred.length === 0 ? <p className="notice">No supplier is on the preferred list for this item on this date
            (no Active supplier bought it in the last 548 days or holds a contract for it). Sourcing would use the category top-ups below.</p> : (
            <table>
              <thead><tr><th>#</th><th>Supplier</th><th>Score</th><th>POs</th><th>Recency</th><th>Contract</th><th>On-time</th><th>Quality</th><th>Reference price</th><th></th></tr></thead>
              <tbody>{result.preferred.map((m) => (
                <tr key={m.supplier_id}><td>{m.rank}</td><td>{m.supplier_id} {m.name}</td><td><b>{m.score}</b></td>
                  <td>{m.parts.po_count}</td><td>{m.parts.recency}</td><td>{m.parts.contract_held}</td><td>{m.parts.on_time}</td>
                  <td>{m.parts.quality}</td><td>{inr(m.reference_price)} <span className="muted">{m.reference}</span></td>
                  <td>{m.exported && <span className="badge good">in the export</span>}</td></tr>))}</tbody>
            </table>
          )}
          <p className="muted">Score = {result.weights.po_count} × POs in 548 days + {result.weights.recency} × recency +
            {" "}{result.weights.contract_held} × contract held + {result.weights.on_time} × on-time %/100 + {result.weights.quality} × quality/5
            (DECISIONS.md D24). Equal scores go to the lower supplier id.</p>
          {result.topups.length > 0 && (
            <>
              <h3>Category top-ups (used only to fill sourcing suggestions, 6.4)</h3>
              <table>
                <thead><tr><th>Supplier</th><th>Score</th><th>On-time</th><th>Quality</th></tr></thead>
                <tbody>{result.topups.map((t) => <tr key={t.supplier_id}><td>{t.supplier_id} {t.name}</td><td>{t.score}</td>
                  <td>{t.parts.on_time}</td><td>{t.parts.quality}</td></tr>)}</tbody>
              </table>
            </>
          )}
        </section>
      )}
    </main>
  );
}
