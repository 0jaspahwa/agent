import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import emptyPolicies from "./fixtures/empty/policies.json";
import emptyRuns from "./fixtures/empty/runs.json";
import policies from "./fixtures/sample/policies.json";
import runs from "./fixtures/sample/runs.json";
import { mockFetch, renderApp } from "./helpers.jsx";

const RESULT = { run_id: 9, batch_id: 3, filename: "blind.csv", lines: 186, requirements: 149, purchase_orders: 72,
  summary_by_route: { SPOT_PO: 72, RFQ: 53 }, policy_mode: { mode: "named_version", version: "5.0" },
  export_url: "/api/runs/9/export.csv", processing_seconds: 1.4, decisions: [] };

describe("batch screen (B5)", () => {
  it("renders on an empty database", async () => {
    mockFetch({ "GET /api/runs": emptyRuns, "GET /api/policies": emptyPolicies });
    renderApp({ role: "Buyer", path: "/batches" });
    expect(await screen.findByText("No runs yet.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Process" }).disabled).toBe(true); // nothing chosen yet
  });

  it("renders the earlier runs with their downloads", async () => {
    mockFetch({ "GET /api/runs": runs, "GET /api/policies": policies });
    renderApp({ role: "Buyer", path: "/batches" });
    const table = (await screen.findAllByRole("table")).at(-1);
    expect(within(table).getAllByRole("row").length - 1).toBe(runs.length);
    expect(within(table).getAllByRole("link", { name: "CSV" })[0].getAttribute("href")).toBe(`/api/runs/${runs[0].run_id}/export.csv`);
  });

  it("processes a file under a named version and offers the CSV and the workspace", async () => {
    const fetch = mockFetch({ "GET /api/runs": runs, "GET /api/policies": policies, "POST /api/process-batch": RESULT });
    renderApp({ role: "Procurement", path: "/batches" });
    await screen.findByText(/Only version 5.0/);
    const file = new File(["pr_no,pr_line\n"], "blind.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText(/CSV file/), { target: { files: [file] } });
    fireEvent.change(screen.getByLabelText("Policy"), { target: { value: "5.0" } });
    fireEvent.submit(screen.getByRole("button", { name: "Process" }).closest("form"));
    expect(await screen.findByText("Run 9: blind.csv")).toBeTruthy();
    const sent = fetch.calls.find((c) => c.method === "POST").body;
    expect(sent.get("policy_version")).toBe("5.0");
    expect(sent.get("file").name).toBe("blind.csv");
    expect(screen.getByRole("link", { name: "Download the decisions CSV" }).getAttribute("href")).toBe("/api/runs/9/export.csv");
    expect(screen.getByRole("link", { name: "Open in the workspace" }).getAttribute("href")).toBe("/workspace?run=9");
  });

  it("a requester does not see Batches", () => {
    mockFetch({ "POST /api/chat/conversations": { id: 1, status: "open", messages: [], draft: { lines: [] }, missing: [], choices: [] } });
    renderApp({ role: "Requester", path: "/chat" });
    expect(screen.queryByRole("link", { name: "Batches" })).toBeNull();
  });
});
