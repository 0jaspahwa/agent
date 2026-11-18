import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { ErrorNote } from "../components/Dialog.jsx";
import { formatDate } from "./Chat.jsx";

const ROUTE_WORDS = {
  CONTRACT_PO: "contract PO", EMERGENCY_PO: "emergency PO", SPOT_PO: "spot PO", RFQ: "RFQ", RFP: "RFP",
  CAPEX_SOURCING: "Capex sourcing", NEW_ITEM_SOURCING: "new-item sourcing", NOT_PROCESSED: "not processed",
};

// B3: the requester's PRs made in chat, with what is happening to each line.
export default function MyRequests() {
  const [prs, setPrs] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { api("/api/chat/requests").then(setPrs, setError); }, []);
  return (
    <main>
      <h1>My requests</h1>
      <ErrorNote error={error} />
      {prs && prs.length === 0 && <p>You have not raised any requests yet. <Link to="/chat">Raise one</Link>.</p>}
      {prs && prs.map((pr) => (
        <section className="card" key={pr.pr_no}>
          <h2>{pr.pr_no} <span className="muted">· {pr.plant} · needed by {formatDate(pr.need_by)} · {pr.urgency}</span></h2>
          <table>
            <thead><tr><th>Line</th><th>Item</th><th>Quantity</th><th>Status</th><th>Route</th></tr></thead>
            <tbody>
              {pr.lines.map((l) => (
                <tr key={l.line}>
                  <td>{l.line}</td><td>{l.item_code} {l.description}</td><td>{l.quantity} {l.unit}</td>
                  <td>{l.status}</td><td>{ROUTE_WORDS[l.route] || "-"}{l.group_id && <span className="muted"> ({l.group_id})</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
      {prs && prs.length > 0 && <p><Link to="/chat">Raise another request</Link></p>}
    </main>
  );
}
