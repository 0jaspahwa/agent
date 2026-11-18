import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Confirm } from "./Dialog.jsx";

const EMPTY = { contract_id: "", supplier_id: "", start_date: "", end_date: "", value_cap: "", lines: [{ item_code: "", rate: "" }] };

// The contract form, filled from a PDF or by hand. Save asks for confirmation; the server checks everything and
// any problems are listed as plain sentences.
export default function ContractForm({ initial, source, sourceFile, onSaved, onCancel }) {
  const [form, setForm] = useState(() => ({ ...EMPTY, ...(initial || {}), lines: (initial?.lines?.length ? initial.lines : EMPTY.lines) }));
  const [items, setItems] = useState([]);
  const [suppliers, setSuppliers] = useState([]);
  const [confirming, setConfirming] = useState(false);
  const [problems, setProblems] = useState([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api("/api/items").then(setItems, () => setItems([]));
    api("/api/suppliers").then(setSuppliers, () => setSuppliers([]));
  }, []);

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const setLine = (i, key) => (e) => setForm({ ...form, lines: form.lines.map((l, j) => (j === i ? { ...l, [key]: e.target.value } : l)) });
  const itemOf = (code) => items.find((it) => it.item_code === code);

  async function save() {
    setBusy(true);
    setProblems([]);
    try {
      const body = { form: { ...form, lines: form.lines.map((l) => ({ ...l, uom: l.uom || itemOf(l.item_code)?.uom })) }, source,
        source_file: sourceFile || null };
      onSaved(await api("/api/contracts", { method: "POST", body }));
    } catch (e) {
      setProblems([e.message]);
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); setConfirming(true); }}>
      <div className="filters">
        <label>Contract number <input value={form.contract_id} onChange={set("contract_id")} placeholder="RC-2026-031" /></label>
        <label>Supplier <select value={form.supplier_id} onChange={set("supplier_id")}>
          <option value="">Choose</option>
          {suppliers.map((s) => <option key={s.supplier_id} value={s.supplier_id}>{s.supplier_id} {s.name}{s.status !== "Active" ? ` (${s.status})` : ""}</option>)}
        </select></label>
        <label>Valid from <input type="date" value={form.start_date} onChange={set("start_date")} /></label>
        <label>to <input type="date" value={form.end_date} onChange={set("end_date")} /></label>
        <label>Ceiling (₹) <input type="number" min="0" step="0.01" value={form.value_cap} onChange={set("value_cap")} /></label>
      </div>
      <table>
        <thead><tr><th>Item</th><th>Unit</th><th>Rate (₹)</th><th></th></tr></thead>
        <tbody>{form.lines.map((l, i) => (
          <tr key={i}>
            <td><select aria-label={`Item ${i + 1}`} value={l.item_code} onChange={setLine(i, "item_code")}>
              <option value="">Choose an item</option>
              {items.map((it) => <option key={it.item_code} value={it.item_code}>{it.item_code} {it.description}</option>)}
            </select></td>
            <td>{l.uom || itemOf(l.item_code)?.uom || ""}</td>
            <td><input aria-label={`Rate ${i + 1}`} type="number" min="0" step="0.01" value={l.rate} onChange={setLine(i, "rate")} /></td>
            <td>{form.lines.length > 1 && <button type="button" className="link" onClick={() => setForm({ ...form, lines: form.lines.filter((_, j) => j !== i) })}>Remove</button>}</td>
          </tr>))}</tbody>
      </table>
      <p><button type="button" className="link" onClick={() => setForm({ ...form, lines: [...form.lines, { item_code: "", rate: "" }] })}>Add an item</button></p>
      {problems.length > 0 && <div className="error" role="alert">{problems.map((p) => <p key={p}>{p}</p>)}</div>}
      <div className="actions">
        <button type="submit" className="primary">Save contract</button>
        <button type="button" onClick={onCancel}>Cancel</button>
      </div>
      {confirming && (
        <Confirm title={`Save ${form.contract_id || "this contract"}?`} confirmLabel="Save" busy={busy}
          onClose={() => setConfirming(false)} onConfirm={save}>
          <p>{form.lines.length} item(s) with {form.supplier_id || "?"}, valid {form.start_date || "?"} to {form.end_date || "?"}.
            It starts with nothing consumed and applies to every run made after it is saved.</p>
        </Confirm>
      )}
    </form>
  );
}
