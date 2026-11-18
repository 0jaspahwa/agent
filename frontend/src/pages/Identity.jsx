import { useState } from "react";
import { ROLES } from "../identity.js";

const WHAT = {
  Requester: "raise purchase requests in a chat and follow them",
  Buyer: "review and act on the decisions, run batches, manage contracts",
  Procurement: "everything a buyer does, plus approve policy changes",
};

// The first screen: who are you? No password; the name and role are recorded with every action.
export default function Identity({ current, onDone }) {
  const [name, setName] = useState(current?.name || "");
  const [role, setRole] = useState(current?.role || "");
  const ready = name.trim() && role;
  return (
    <main className="narrow">
      <h1>Corvo procurement</h1>
      <p>Tell us who you are. Your name and role are recorded with everything you do here.</p>
      <form onSubmit={(e) => { e.preventDefault(); if (ready) onDone({ name: name.trim(), role }); }}>
        <label>Your name <input value={name} onChange={(e) => setName(e.target.value)} autoFocus /></label>
        <fieldset>
          <legend>Your role</legend>
          {ROLES.map((r) => (
            <label key={r} className="choice">
              <input type="radio" name="role" value={r} checked={role === r} onChange={() => setRole(r)} />
              <b>{r}</b>: {WHAT[r]}
            </label>
          ))}
        </fieldset>
        <button type="submit" className="primary" disabled={!ready}>Continue</button>
      </form>
      <p className="muted">No login: this is a demo. The role decides which screens you see.</p>
    </main>
  );
}
