import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import App from "../App.jsx";

// A fake fetch: `routes` maps "GET /api/runs" (query string ignored unless given) to a value, or to a function
// (request) => value. A value {status, body} sets the status. Every call is recorded in fetchMock.calls.
export function mockFetch(routes) {
  const calls = [];
  const fn = vi.fn(async (url, options = {}) => {
    const method = options.method || "GET";
    const path = String(url);
    const request = { method, path, headers: options.headers || {}, body: options.body };
    calls.push(request);
    const key = Object.keys(routes).find((k) => k === `${method} ${path}`)
      || Object.keys(routes).find((k) => k === `${method} ${path.split("?")[0]}`);
    let out = key ? routes[key] : { status: 404, body: { detail: `No fake for ${method} ${path}` } };
    if (typeof out === "function") out = await out(request);
    const status = out && out.status && out.body !== undefined ? out.status : 200;
    const body = out && out.status && out.body !== undefined ? out.body : out;
    return { ok: status < 400, status, text: async () => (typeof body === "string" ? body : JSON.stringify(body ?? null)) };
  });
  fn.calls = calls;
  vi.stubGlobal("fetch", fn);
  return fn;
}

export function renderApp({ role = "Buyer", name = "Asha", path = "/" } = {}) {
  const identity = role ? { name, role } : null;
  return render(<App initialIdentity={identity} Router={MemoryRouter} routerProps={{ initialEntries: [path] }} />);
}
