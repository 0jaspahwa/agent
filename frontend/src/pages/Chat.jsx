import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { Confirm, ErrorNote } from "../components/Dialog.jsx";

const KEY = "corvo.chat";

function remembered() {
  try {
    return window.sessionStorage.getItem(KEY);
  } catch {
    return null; // storage blocked: a reload starts a new conversation
  }
}

function remember(id) {
  try {
    if (id) window.sessionStorage.setItem(KEY, String(id));
    else window.sessionStorage.removeItem(KEY);
  } catch {
    // storage blocked: nothing to remember
  }
}

// B3: chat intake. The conversation on the left, the draft PR on the right filling in as fields are captured,
// so the requester always sees what is still missing. Enter sends the message and does nothing else; the one
// action on the card is Create, which asks for confirmation.
export default function Chat() {
  const [conv, setConv] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  // A reload in the middle of a request continues it (the conversation is kept on the server; this tab keeps
  // its id). A finished or someone else's conversation is not resumed: a new one starts.
  async function start(fresh = false) {
    setError(null);
    try {
      const id = fresh ? null : remembered();
      if (id) {
        const open = await api(`/api/chat/conversations/${id}`).catch(() => null);
        if (open && open.status === "open") {
          setConv(open);
          return;
        }
      }
      const created = await api("/api/chat/conversations", { method: "POST" });
      remember(created.id);
      setConv(created);
    } catch (e) {
      setError(e);
    }
  }
  useEffect(() => { start(); }, []);

  async function send(payload) {
    setBusy(true);
    setError(null);
    try {
      const next = await api(`/api/chat/conversations/${conv.id}/messages`, { method: "POST", body: payload });
      if (next.status !== "open") remember(null);
      setConv(next);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  if (!conv) return <main><h1>New request</h1><ErrorNote error={error} />{!error && <p>Starting...</p>}</main>;
  const open = conv.status === "open";
  return (
    <main>
      <h1>New request</h1>
      <div className="grid2">
        <ChatPanel conv={conv} busy={busy} open={open} onSend={(text) => send({ text })} onEvent={(event) => send({ event })} />
        <DraftPanel conv={conv} busy={busy} onCreate={() => send({ event: { type: "create", label: "Create" } })} onNew={() => start(true)} />
      </div>
      <ErrorNote error={error} />
    </main>
  );
}

function ChatPanel({ conv, busy, open, onSend, onEvent }) {
  const [text, setText] = useState("");
  const log = useRef(null);
  useEffect(() => { log.current?.scrollTo?.(0, log.current.scrollHeight); }, [conv.messages.length]);
  return (
    <section className="chat" aria-label="Conversation">
      <div className="log" ref={log}>
        {conv.messages.map((m, i) => (
          <div key={i} className={`bubble ${m.sender}`}>
            {m.text}
            {m.link && <> <Link to={m.link}>Open the draft</Link></>}
          </div>
        ))}
        {open && conv.choices.length > 0 && (
          <div className="chips">
            {conv.choices.map((c, i) => (
              <button key={i} type="button" disabled={busy}
                onClick={() => (c.type === "message" ? onSend(c.text) : onEvent({ ...c, label: c.label }))}>
                {c.label}
              </button>
            ))}
          </div>
        )}
      </div>
      {open && (
        <form onSubmit={(e) => { e.preventDefault(); if (text.trim() && !busy) { onSend(text.trim()); setText(""); } }}>
          <input aria-label="Message" value={text} onChange={(e) => setText(e.target.value)} disabled={busy}
            placeholder="e.g. 200 nitrile gloves for Chakan by next Friday" autoFocus />
          <button type="submit" disabled={busy || !text.trim()}>Send</button>
        </form>
      )}
    </section>
  );
}

function DraftPanel({ conv, busy, onCreate, onNew }) {
  const [confirming, setConfirming] = useState(false);
  const d = conv.draft;
  if (conv.status !== "open") {
    return (
      <section className="card" aria-label="Result">
        <h2>{conv.status === "created" ? `Created ${conv.pr_no}` : conv.status === "cancelled" ? "Discarded" : "Policy draft started"}</h2>
        <p>{conv.messages[conv.messages.length - 1].text}</p>
        <div className="actions">
          <button type="button" className="primary" onClick={onNew}>Start another request</button>
          <Link to="/requests">My requests</Link>
        </div>
      </section>
    );
  }
  return (
    <section className={`card ${conv.card ? "selected" : ""}`} aria-label="Draft request">
      <h2>{conv.card ? "Check your request" : "Your request so far"}</h2>
      {d.lines.length === 0 ? <p className="muted">No item yet.</p> : (
        <table>
          <thead><tr><th>#</th><th>Item</th><th>Quantity</th></tr></thead>
          <tbody>
            {d.lines.map((l) => (
              <tr key={l.line}>
                <td>{l.line}</td>
                <td>{l.new_item ? <><span className="badge warn">new item</span> {l.description}
                  {l.estimated_unit_price && <> · est. ₹{l.estimated_unit_price} each</>}</>
                  : l.item_code === "NEW" ? <span className="muted">{l.description} (not matched yet)</span>
                    : <>{l.item_code} {l.description}</>}</td>
                <td>{l.quantity ? `${l.quantity} ${l.unit || ""}` : <span className="muted">?</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <dl className="facts">
        <dt>Plant</dt><dd>{d.plant ? `${d.plant_name} (${d.plant})` : <span className="muted">?</span>}</dd>
        <dt>Need by</dt><dd>{d.need_by ? formatDate(d.need_by) : <span className="muted">?</span>}</dd>
        <dt>Urgency</dt><dd>{d.urgency}</dd>
      </dl>
      {conv.missing.length > 0 && <p className="warn">Still needed: {conv.missing.join(", ")}.</p>}
      {conv.card && (
        <div className="actions">
          <button type="button" className="primary" disabled={busy} onClick={() => setConfirming(true)}>Create</button>
          <span className="muted">or type what to change</span>
        </div>
      )}
      {confirming && (
        <Confirm title="Create this request?" confirmLabel="Create" busy={busy}
          onClose={() => setConfirming(false)} onConfirm={() => { setConfirming(false); onCreate(); }}>
          <p>{d.lines.length} line{d.lines.length > 1 ? "s" : ""} for {d.plant_name}, needed by{" "}
            {formatDate(d.need_by)} ({d.urgency}). A buyer reviews it before anything is ordered.</p>
        </Confirm>
      )}
    </section>
  );
}

export function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}
