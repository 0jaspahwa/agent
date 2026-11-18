import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { mockFetch, renderApp } from "./helpers.jsx";
import nokitHealth from "./fixtures/nokit/health.json";
import loadedHealth from "./fixtures/empty/health.json";
import kitLoad from "./fixtures/nokit/kit_load.json";

// Load kit data (Procurement): the kit is not in the repo, so it is uploaded once after deploying.
describe("load kit data", () => {
  it("uploads the chosen files, shows what was loaded, and the banner goes away", async () => {
    let loaded = false;
    const fetch = mockFetch({
      "GET /api/health": () => (loaded ? loadedHealth : nokitHealth),
      "POST /api/admin/load-kit": () => { loaded = true; return kitLoad; },
    });
    renderApp({ role: "Procurement", name: "Ojas", path: "/kit" });
    expect(await screen.findByText(/No kit data loaded/)).toBeTruthy();
    const button = screen.getByRole("button", { name: "Load kit data" });
    expect(button.disabled).toBe(true);
    const zip = new File(["PK"], "Cantill_FullStack_Task_Kit_vf.zip", { type: "application/zip" });
    fireEvent.change(screen.getByLabelText("Kit zip or files"), { target: { files: [zip] } });
    fireEvent.click(screen.getByRole("button", { name: "Load kit data" }));
    expect(await screen.findByText(kitLoad.message)).toBeTruthy();
    const sent = fetch.calls.find((c) => c.method === "POST");
    expect(sent.path).toBe("/api/admin/load-kit");
    expect(sent.body.getAll("files").map((f) => f.name)).toEqual(["Cantill_FullStack_Task_Kit_vf.zip"]);
    expect(sent.headers["X-Role"]).toBe("Procurement");
    expect(screen.getByText("items").closest("tr").textContent).toContain("73");
    expect(screen.getByText(/sample_pr_batch.csv: a PR batch is processed under Batches/)).toBeTruthy();
    await waitFor(() => expect(screen.queryByText(/No kit data loaded/)).toBeNull());
  });

  it("says plainly why a kit was refused", async () => {
    mockFetch({
      "GET /api/health": nokitHealth,
      "POST /api/admin/load-kit": { status: 400, body: { detail: "The kit is incomplete: master_data/po_history.csv missing." } },
    });
    renderApp({ role: "Procurement", path: "/kit" });
    fireEvent.change(await screen.findByLabelText("Kit zip or files"), { target: { files: [new File(["x"], "kit.zip")] } });
    fireEvent.click(screen.getByRole("button", { name: "Load kit data" }));
    expect((await screen.findByRole("alert")).textContent).toBe("The kit is incomplete: master_data/po_history.csv missing.");
  });

  it("is a Procurement screen only", async () => {
    mockFetch({ "GET /api/health": nokitHealth, "GET /api/workspace/runs": [] });
    renderApp({ role: "Buyer", path: "/kit" });
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Load kit data" })).toBeNull());
    expect(await screen.findByText(/No kit data loaded/)).toBeTruthy();
  });
});
