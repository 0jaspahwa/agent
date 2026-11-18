import { useState } from "react";
import { api, inr, qty } from "../api.js";
import { ApproveDialog, OverrideDialog } from "./ActionDialogs.jsx";
import { ErrorNote } from "./Dialog.jsx";

// One requirement: its PR lines, the decision in words, the value, the supplier and price or the suggested
// suppliers, and why. Approve is the primary action; Override is secondary. Once actioned, the outcome replaces
// the buttons.
export default function RequirementDetail({ req, all, onDone, onConflict }) {
  const [dialog, setDialog] = useState(null);
  const [showRanking, setShowRanking] = useState(false);
  const [error, setError] = useState(null);
  const isPo = req.decision === "PO";
  const onPo = req.po ? req.po.requirements.map((m) => all.find((r) => r.id === m.id)).filter(Boolean) : [req];
  const openOnPo = onPo.filter((r) => r.status === "open");

  async function approve() {
    try {
      const versions = Object.fromEntries((req.po ? openOnPo : [req]).map((r) => [r.id, r.version]));
      const out = await api(`/api/requirements/${req.id}/approve`, { method: "POST", body: { versions } });
      setDialog(null);
      const rec = out.record;
      onDone(rec.kind === "po" ? `Approved ${rec.po_number}: ${rec.lines.filter((l) => l.approved).length} line(s) to ${rec.supplier_id}, total ${inr(rec.total_value)}.`
        : `Approved: ${rec.route} issued for ${rec.group_id} with ${rec.suggested_supplier_ids.length} suggested supplier(s).`);
    } catch (e) {
      setDialog(null);
      if (e.status === 409) onConflict(e); else setError(e);
    }
  }

  return (
    <article className="card">
      <h2>{req.group_id}: {req.item_description}</h2>
      <p>
        <span className="badge">{req.route_words}</span> · {qty(req.total_quantity)} {req.unit} at {req.plant} ·
        value <b>{inr(req.value_inr)}</b> · requirement date {req.requirement_date}
      </p>

      <ErrorNote error={error} />
      {req.status === "open" ? (
        <div className="actions">
          <button type="button" className="primary" onClick={() => setDialog("approve")}>
            {req.po && openOnPo.length > 1 ? `Approve PO (${openOnPo.length} requirements)` : "Approve"}</button>
          <button type="button" onClick={() => setDialog("override")}>Override</button>
        </div>
      ) : (
        <p className="notice">This requirement is {req.status}; see its history below. It cannot be actioned again.</p>
      )}
      <h3>Decision</h3>
      {isPo ? (
        <dl className="facts">
          <dt>Supplier</dt><dd>{req.supplier.supplier_id} {req.supplier.name}</dd>
          <dt>Unit price</dt><dd>{inr(req.unit_price)}</dd>
          {req.po && <><dt>PO</dt><dd>{req.po.po_number} ({req.po.status}){req.po.requirements.length > 1 &&
            <> · consolidated with {req.po.requirements.filter((m) => m.id !== req.id).map((m) => m.group_id).join(", ")}</>}</dd></>}
          {req.contract_id && <><dt>Contract</dt><dd>{req.contract_id}</dd></>}
        </dl>
      ) : (
        <>
          <p>{req.suggestions.length === 0 ? "No suppliers to suggest." : "Suggested suppliers, in order:"}</p>
          {req.suggestions.length > 0 && <ol>{req.suggestions.map((s) => (
            <li key={s.supplier_id}>{s.supplier_id} {s.name} <span className="muted">({s.source})</span></li>))}</ol>}
        </>
      )}

      <h3>Why</h3>
      <dl className="facts">
        <dt>Clause</dt><dd>{req.why.clause} (policy v{req.policy_version})</dd>
        <dt>Value from</dt><dd>{req.why.price_source_words}{req.why.price_reference && ` (${req.why.price_reference})`}</dd>
      </dl>
      <p className="muted">{req.why.reason}</p>
      {req.flags.length > 0 && <ul>{req.flags.map((f) => <li key={f.code} className="warn">{f.code}: {f.text}</li>)}</ul>}
      {req.preferred.length > 0 && (
        <p><button type="button" className="link" onClick={() => setShowRanking(!showRanking)}>
          {showRanking ? "Hide" : "Why this supplier"}: the preferred list and its scores</button></p>
      )}
      {showRanking && <Ranking rows={req.preferred} />}

      <h3>PR lines</h3>
      <table>
        <thead><tr><th>PR</th><th>Qty</th><th>Need by</th><th>Urgency</th><th>Requester</th></tr></thead>
        <tbody>{req.lines.map((l) => (
          <tr key={`${l.pr_no}/${l.pr_line}`}><td>{l.pr_no}/{l.pr_line}</td><td>{qty(l.quantity)} {l.uom}</td><td>{l.need_by}</td>
            <td>{l.urgency}</td><td>{l.requester}{l.department && ` (${l.department})`}</td></tr>))}</tbody>
      </table>

      {req.history.length > 0 && (
        <>
          <h3>History</h3>
          <ul>{req.history.map((h, i) => (
            <li key={i}><b>{h.action === "approve" ? "Approved" : "Overridden"}</b> by {h.by} ({h.role}) at {String(h.at).slice(0, 16).replace("T", " ")}
              {h.action === "override" && <> → {h.new_route}{h.new_supplier_id && ` with ${h.new_supplier_id} at ${inr(h.new_unit_price)}`}
                {h.new_suggested_supplier_ids?.length > 0 && ` suggesting ${h.new_suggested_supplier_ids.join(", ")}`}: "{h.comment}"</>}</li>))}</ul>
        </>
      )}

      {dialog === "approve" && <ApproveDialog req={req} group={req.po ? openOnPo : [req]} onConfirm={approve} onClose={() => setDialog(null)} />}
      {dialog === "override" && <OverrideDialog req={req} onClose={() => setDialog(null)}
        onDone={(msg) => { setDialog(null); onDone(msg); }} onConflict={(e) => { setDialog(null); onConflict(e); }} />}
    </article>
  );
}

function Ranking({ rows }) {
  return (
    <table>
      <thead><tr><th>#</th><th>Supplier</th><th>Score</th><th>POs</th><th>Recency</th><th>Contract</th><th>On-time</th><th>Quality</th><th>Ref. price</th></tr></thead>
      <tbody>{rows.map((p) => (
        <tr key={p.supplier_id}><td>{p.rank}</td><td>{p.supplier_id} {p.name}</td><td><b>{p.score}</b></td>
          <td>{p.parts.po_count}</td><td>{p.parts.recency}</td><td>{p.parts.contract_held}</td><td>{p.parts.on_time}</td>
          <td>{p.parts.quality}</td><td>{inr(p.reference_price)} <span className="muted">{p.reference}</span></td></tr>))}</tbody>
      <tfoot><tr><td colSpan="9" className="muted">Score = 1 × POs in 548 days + 5 × recency + 2 × contract held +
        on-time %/100 + quality/5 (DECISIONS.md D24). Ties go to the lower supplier id.</td></tr></tfoot>
    </table>
  );
}
