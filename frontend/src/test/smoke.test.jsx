import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { mockFetch, renderApp } from "./helpers.jsx";

// Every screen, for every role, on an empty database and on the sample batch, from the real API's responses
// (scripts/make_ui_fixtures.py). A screen must render its heading without crashing and without an error.
const fixtures = import.meta.glob("./fixtures/*/*.json", { eager: true, import: "default" });
const load = (state, name) => fixtures[`./fixtures/${state}/${name}.json`] ?? fixtures[`./fixtures/empty/${name}.json`];

function routes(state) {
  const f = (name) => load(state, name);
  const chat = { id: 1, status: "open", pr_no: null, messages: [{ sender: "assistant", text: "Hello. What do you need?" }],
    pending: null, draft: { lines: [], plant: null, plant_name: null, need_by: null, urgency: "Normal" }, missing: ["item"], choices: [], card: null };
  return {
    "GET /api/workspace/runs": f("workspace_runs"), "GET /api/workspace": f("workspace"), "GET /api/chat/requests": f("my_requests"),
    "POST /api/chat/conversations": chat, "GET /api/suppliers": f("suppliers"), "GET /api/runs": f("runs"),
    "GET /api/policies": f("policies"), "GET /api/policies/1": f("policy_1"), "GET /api/contracts": f("contracts"),
    "GET /api/items": f("items"), "GET /api/audit": f("audit"), "GET /api/health": f("health"),
  };
}

const SCREENS = {
  Requester: { "/chat": "New request", "/requests": "My requests" },
  Buyer: { "/workspace": "Workspace", "/batches": "Batches", "/contracts": "Contracts", "/suppliers": "Preferred suppliers", "/audit": "Audit log" },
  Procurement: { "/workspace": "Workspace", "/batches": "Batches", "/contracts": "Contracts", "/suppliers": "Preferred suppliers",
    "/policies": "Policy", "/audit": "Audit log", "/chat": "New request", "/requests": "My requests", "/policies/1": "Policy version 5.0",
    "/kit": "Load kit data" },
};

describe("every screen renders (smoke)", () => {
  for (const state of ["nokit", "empty", "sample"]) {
    for (const [role, screens] of Object.entries(SCREENS)) {
      for (const [path, heading] of Object.entries(screens)) {
        it(`${role} ${path} on the ${state} database`, async () => {
          mockFetch(routes(state));
          renderApp({ role, path });
          expect(await screen.findByRole("heading", { level: 1, name: new RegExp(heading) })).toBeTruthy();
          await waitFor(() => expect(screen.queryByText(/Loading|Starting/)).toBeNull());
          expect(screen.queryByRole("alert")).toBeNull();
          if (state === "nokit") {
            expect(await screen.findByText("No kit data loaded. Procurement: load it under Load kit data.")).toBeTruthy();
            expect(screen.queryAllByRole("link", { name: "Load kit data" }).length > 0).toBe(role === "Procurement");
          } else {
            await waitFor(() => expect(fetch.calls.some((c) => c.path === "/api/health")).toBe(true));
            expect(screen.queryByText(/No kit data loaded/)).toBeNull();
          }
        });
      }
    }
  }

  it("each role's navigation shows exactly its own screens", () => {
    const tabs = { Requester: ["New request", "My requests"],
      Buyer: ["Workspace", "Batches", "Contracts", "Preferred suppliers", "Audit log"],
      Procurement: ["Workspace", "Batches", "Contracts", "Preferred suppliers", "Policy", "Audit log", "Load kit data",
        "New request", "My requests"] };
    for (const [role, expected] of Object.entries(tabs)) {
      mockFetch(routes("empty"));
      const { unmount } = renderApp({ role, path: "/" });
      const nav = screen.getByRole("navigation");
      expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual(expected);
      unmount();
    }
  });
});

describe("preferred suppliers and audit log (B8, B9)", () => {
  it("shows the ranked list with score parts and marks the exported top 3", async () => {
    const preferred = load("sample", "preferred");
    mockFetch({ ...routes("sample"), "GET /api/preferred-suppliers": preferred });
    renderApp({ role: "Buyer", path: "/suppliers" });
    fireEvent.change(await screen.findByLabelText("Item"), { target: { value: "ITM-1048" } });
    fireEvent.click(screen.getByRole("button", { name: "Show the list" }));
    const list = await screen.findByRole("region", { name: "Preferred list" });
    expect(within(list).getAllByText("in the export").length).toBe(preferred.preferred.filter((m) => m.exported).length);
    expect(screen.getByRole("link", { name: /Download the CSV/ }).getAttribute("href")).toMatch(/export\.csv\?as_of=/);
  });

  it("the audit log filters by who and asks the server again", async () => {
    const audit = load("sample", "audit");
    const fetch = mockFetch(routes("sample"));
    renderApp({ role: "Procurement", path: "/audit" });
    fireEvent.change(await screen.findByLabelText("Who"), { target: { value: audit.actors[0] } });
    await waitFor(() => expect(fetch.calls.some((c) => c.path === `/api/audit?actor=${encodeURIComponent(audit.actors[0])}`)).toBe(true));
  });
});
