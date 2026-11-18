// The one place that talks to the server. Adds the name and role to every request, and turns every failure
// into a plain sentence (never a stack trace or raw JSON).

let identity = null;

export function setApiIdentity(value) {
  identity = value;
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

const FALLBACK = {
  400: "The request could not be used.",
  403: "Your role cannot do this.",
  404: "That could not be found. It may have been removed.",
  409: "Someone else changed this first. The page has been refreshed.",
  422: "Some details are missing or not valid.",
  500: "Something went wrong on the server. Try again; if it keeps happening, use the operations pages at /ops.",
  503: "A service the app needs is unavailable right now.",
};

export function plainMessage(data, status) {
  const detail = data && typeof data === "object" ? data.detail : null;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length) {
    // FastAPI field errors: "quantity: value is not a valid number"
    return detail.map((d) => `${(d.loc || []).filter((x) => x !== "body").join(" ")}: ${d.msg}`).join("; ");
  }
  return FALLBACK[status] || (status >= 500 ? FALLBACK[500] : "The request did not work.");
}

export async function api(path, { method = "GET", body, form } = {}) {
  const headers = {};
  if (identity) {
    headers["X-User"] = encodeURIComponent(identity.name); // headers must be plain ASCII; the server decodes
    headers["X-Role"] = identity.role;
  }
  let payload;
  if (form) payload = form;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, { method, headers, body: payload });
  } catch {
    throw new ApiError("The server could not be reached. Check the connection and try again "
      + "(the hosted demo can take up to a minute to wake up).", 0);
  }
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!response.ok) throw new ApiError(plainMessage(data, response.status), response.status);
  return data;
}

// Formats shared by every screen.
export function inr(value) {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  return Number.isFinite(n)
    ? "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : String(value);
}

export function qty(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString("en-IN", { maximumFractionDigits: 3 }) : String(value ?? "");
}
