// Who is using the app. There is no login (DECISIONS.md D35): the first screen asks for a name and a role, they
// are kept in this browser, and api.js sends them with every request. The server records them in the audit log.

export const ROLES = ["Requester", "Buyer", "Procurement"];

const KEY = "corvo.identity";

export function loadIdentity() {
  try {
    const value = JSON.parse(window.localStorage.getItem(KEY) || "null");
    return value && value.name && ROLES.includes(value.role) ? value : null;
  } catch {
    return null; // storage blocked (private window): ask again
  }
}

export function saveIdentity(identity) {
  try {
    if (identity) window.localStorage.setItem(KEY, JSON.stringify(identity));
    else window.localStorage.removeItem(KEY);
  } catch {
    // storage blocked: the identity still lives for this page load
  }
}
