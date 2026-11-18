import { useEffect, useState } from "react";
import { api, inr, qty } from "../api.js";
import { Confirm, Dialog, ErrorNote } from "./Dialog.jsx";

const PO_ROUTES = ["CONTRACT_PO", "EMERGENCY_PO", "SPOT_PO"];
const ROUTES = [...PO_ROUTES, "RFQ", "RFP", "CAPEX_SOURCING", "NEW_ITEM_SOURCING"];

// Approve asks for confirmation; on a consolidated PO it lists every requirement that will be approved with it.
export function ApproveDialog({ req, group, onConfirm, onClose }) {
  const [busy, setBusy] = useState(false);
  const title = req.po ? `Approve ${req.po.po_number}?` : `Approve ${req.group_id}?`;
  return (
    <Confirm title={title} confirmLabel="Approve" busy={busy} onClose={onClose}
      onConfirm={async () => { setBusy(true); await onConfirm(); setBusy(false); }}>
      {req.po ? (
        <>
          <p>This creates PO {req.po.po_number} to {req.po.supplier.supplier_id} {req.po.supplier.name}. Approving it
            approves {group.length > 1 ? "all these requirements together" : "this requirement"}:</p>
          <ul>{group.map((r) => <li key={r.id}>{r.group_id}: {qty(r.total_quantity)} {r.unit} {r.item_description} at {inr(r.unit_price)}</li>)}</ul>
        </>
      ) : (
        <p>This issues the {req.route_words.toLowerCase()} for {req.group_id}
          {req.suggestions.length > 0 && <> to {req.suggestions.map((s) => s.supplier_id).join(", ")}</>}.</p>
      )}
    </Confirm>
  );
}

// Override: a different route or supplier, with a comment. The engine's decision stays visible beside it.
export function OverrideDialog({ req, onClose, onDone, onConflict }) {
  const [route, setRoute] = useState(req.route);
  const [supplierId, setSupplierId] = useState("");
  const [price, setPrice] = useState(req.unit_price || "");
  const [suggested, setSuggested] = useState([]);
  const [comment, setComment] = useState("");
  const [suppliers, setSuppliers] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const query = req.category ? `?category=${encodeURIComponent(req.category)}` : "";
    api(`/api/suppliers${query}`).then(setSuppliers, setError);
  }, [req.category]);
  const isPo = PO_ROUTES.includes(route);
  const ready = comment.trim() && (isPo ? supplierId && Number(price) > 0 : true);

  async function submit(e) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    try {
      await api(`/api/requirements/${req.id}/override`, { method: "POST", body: {
        version: req.version, route, comment, supplier_id: isPo ? supplierId : null, unit_price: isPo ? price : null,
        suggested_supplier_ids: isPo ? [] : suggested } });
      onDone(`Overridden: ${req.group_id} is now ${route}${isPo ? ` with ${supplierId}` : ""}.`);
    } catch (err) {
      if (err.status === 409) onConflict(err); else setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog title={`Override ${req.group_id}`} onClose={onClose}>
      <p className="muted">The engine decided: {req.route_words}{req.supplier && ` with ${req.supplier.supplier_id} at ${inr(req.unit_price)}`}
        {" "}(clause {req.why.clause}). That decision stays on record beside your override.</p>
      <form onSubmit={submit}>
        <label>Route <select value={route} onChange={(e) => setRoute(e.target.value)}>
          {ROUTES.map((r) => <option key={r}>{r}</option>)}</select></label>
        {isPo ? (
          <>
            <label>Supplier <select value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
              <option value="">Choose a supplier</option>
              {suppliers.map((s) => <option key={s.supplier_id} value={s.supplier_id} disabled={s.status !== "Active"}>
                {s.supplier_id} {s.name}{s.status !== "Active" ? ` (${s.status}: cannot receive a PO)` : ""}</option>)}
            </select></label>
            <label>Unit price (₹) <input type="number" min="0" step="0.01" value={price} onChange={(e) => setPrice(e.target.value)} /></label>
          </>
        ) : (
          <fieldset><legend>Suppliers to suggest (optional)</legend>
            {suppliers.filter((s) => s.status === "Active").map((s) => (
              <label key={s.supplier_id} className="choice"><input type="checkbox" checked={suggested.includes(s.supplier_id)}
                onChange={(e) => setSuggested(e.target.checked ? [...suggested, s.supplier_id] : suggested.filter((x) => x !== s.supplier_id))} />
                {s.supplier_id} {s.name}</label>))}
          </fieldset>
        )}
        <label>Why (required) <textarea rows="3" value={comment} onChange={(e) => setComment(e.target.value)} /></label>
        <ErrorNote error={error} />
        <div className="actions">
          <button type="submit" className="primary" disabled={!ready || busy}>{busy ? "Saving..." : "Save override"}</button>
          <button type="button" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </Dialog>
  );
}
