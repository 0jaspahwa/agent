import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import emptyRuns from "./fixtures/empty/workspace_runs.json";
import emptyWs from "./fixtures/empty/workspace.json";
import runs from "./fixtures/sample/workspace_runs.json";
import suppliers from "./fixtures/sample/suppliers.json";
import ws from "./fixtures/sample/workspace.json";
import { mockFetch, renderApp } from "./helpers.jsx";

const consolidated = ws.requirements.find((r) => r.status === "open" && r.po && r.po.requirements.length > 1);
const approved = ws.requirements.find((r) => r.status === "approved");

function sample(extra = {}) {
  return mockFetch({ "GET /api/workspace/runs": runs, "GET /api/workspace": ws, "GET /api/suppliers": suppliers, ...extra });
}

async function open(groupId) {
  fireEvent.click(await screen.findByRole("button", { name: groupId }));
}

describe("buyer workspace (B4)", () => {
  it("renders on an empty database", async () => {
    mockFetch({ "GET /api/workspace/runs": emptyRuns, "GET /api/workspace": emptyWs });
    renderApp({ role: "Buyer", path: "/workspace" });
    expect(await screen.findByText(/No batch has been processed yet/)).toBeTruthy();
  });

  it("renders the sample batch: the queue shows what needs action, and Not processed has its own tab", async () => {
    sample();
    renderApp({ role: "Buyer", path: "/workspace" });
    const queue = await screen.findByRole("region", { name: "Queue" });
    const open = ws.requirements.filter((r) => r.status === "open").length;
    expect(within(queue).getAllByRole("row").length - 1).toBe(open);
    fireEvent.click(within(queue).getByLabelText("Needs action"));
    expect(within(queue).getAllByRole("row").length - 1).toBe(ws.requirements.length);
    fireEvent.click(screen.getByRole("tab", { name: /Not processed/ }));
    for (const np of ws.not_processed) expect(screen.getByText(np.reason)).toBeTruthy();
  });

  it("filters by route", async () => {
    sample();
    renderApp({ role: "Buyer", path: "/workspace" });
    const queue = await screen.findByRole("region", { name: "Queue" });
    fireEvent.change(within(queue).getByLabelText("Route"), { target: { value: "RFP" } });
    const rfps = ws.requirements.filter((r) => r.status === "open" && r.route === "RFP").length;
    expect(within(queue).getAllByRole("row").length - 1).toBe(rfps);
  });

  it("a requirement shows its decision, why, and the supplier ranking with score parts", async () => {
    sample();
    renderApp({ role: "Buyer", path: "/workspace" });
    await open(consolidated.group_id);
    const card = screen.getByRole("region", { name: "Requirement" });
    expect(within(card).getByText(consolidated.why.reason)).toBeTruthy();
    expect(within(card).getByText(/consolidated with/)).toBeTruthy();
    if (consolidated.preferred.length) {
      fireEvent.click(within(card).getByRole("button", { name: /Why this supplier/ }));
      expect(within(card).getByText(/Score = 1 × POs in 548 days/)).toBeTruthy();
    }
  });

  it("approving a consolidated PO confirms every requirement on it and sends all their versions", async () => {
    const fetch = sample({ [`POST /api/requirements/${consolidated.id}/approve`]: { record: { kind: "po", po_number: consolidated.po.po_number,
      supplier_id: consolidated.supplier.supplier_id, lines: [{ approved: true }], total_value: "100.00" }, requirement: consolidated } });
    renderApp({ role: "Buyer", path: "/workspace" });
    await open(consolidated.group_id);
    fireEvent.click(screen.getByRole("button", { name: /^Approve PO \(\d+ requirements\)$/ }));
    const dialog = screen.getByRole("dialog");
    for (const m of consolidated.po.requirements) expect(within(dialog).getByText(new RegExp(`^${m.group_id}:`))).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText(new RegExp(`Approved ${consolidated.po.po_number}`))).toBeTruthy();
    const body = JSON.parse(fetch.calls.find((c) => c.method === "POST").body);
    expect(Object.keys(body.versions).length).toBe(consolidated.po.requirements.length);
  });

  it("when someone else acted first, says so plainly and refreshes", async () => {
    const fetch = sample({ [`POST /api/requirements/${consolidated.id}/approve`]: { status: 409,
      body: { detail: `${consolidated.group_id} was already approved by Kiran. The page has been refreshed.` } } });
    renderApp({ role: "Buyer", path: "/workspace" });
    await open(consolidated.group_id);
    fireEvent.click(screen.getByRole("button", { name: /^Approve/ }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Approve" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/already approved by Kiran/);
    await waitFor(() => expect(fetch.calls.filter((c) => c.path.startsWith("/api/workspace?") || c.path === "/api/workspace").length).toBeGreaterThan(1));
  });

  it("an approved requirement shows its outcome instead of the buttons", async () => {
    sample();
    renderApp({ role: "Buyer", path: "/workspace" });
    const queue = await screen.findByRole("region", { name: "Queue" });
    fireEvent.click(within(queue).getByLabelText("Needs action"));
    await open(approved.group_id);
    const card = screen.getByRole("region", { name: "Requirement" });
    expect(within(card).queryByRole("button", { name: /^Approve/ })).toBeNull();
    expect(within(card).getByText(/cannot be actioned again/)).toBeTruthy();
    expect(within(card).getByText("Approved")).toBeTruthy();
  });

  it("override needs a comment, and a blocked supplier cannot be chosen", async () => {
    sample();
    renderApp({ role: "Buyer", path: "/workspace" });
    const spot = ws.requirements.find((r) => r.status === "open" && r.route === "SPOT_PO");
    await open(spot.group_id);
    fireEvent.click(screen.getByRole("button", { name: "Override" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/The engine decided/)).toBeTruthy();
    const save = within(dialog).getByRole("button", { name: "Save override" });
    expect(save.disabled).toBe(true);
    const blocked = suppliers.find((s) => s.status === "Blocked");
    const option = within(dialog).getAllByRole("option").find((o) => o.value === blocked.supplier_id);
    if (option) expect(option.disabled).toBe(true);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("a requester cannot see the workspace", () => {
    mockFetch({ "POST /api/chat/conversations": { id: 1, status: "open", messages: [], draft: { lines: [] }, missing: [], choices: [] } });
    renderApp({ role: "Requester", path: "/workspace" });
    expect(screen.queryByRole("link", { name: "Workspace" })).toBeNull();
  });
});
