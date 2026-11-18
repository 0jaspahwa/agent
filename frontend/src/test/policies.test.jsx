import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import emptyPolicies from "./fixtures/empty/policies.json";
import emptyRuns from "./fixtures/empty/runs.json";
import draft from "./fixtures/sample/policy_draft.json";
import preview from "./fixtures/sample/policy_preview.json";
import approved from "./fixtures/sample/policy_1.json";
import policies from "./fixtures/sample/policies.json";
import runs from "./fixtures/sample/runs.json";
import { mockFetch, renderApp } from "./helpers.jsx";

const D = `/api/policies/${draft.id}`;

describe("policy screens (B7)", () => {
  it("renders the version list on an empty database and on the sample data", async () => {
    mockFetch({ "GET /api/policies": emptyPolicies });
    const { unmount } = renderApp({ role: "Procurement", path: "/policies" });
    expect(await screen.findByRole("link", { name: "5.0" })).toBeTruthy();
    unmount();
    mockFetch({ "GET /api/policies": policies });
    renderApp({ role: "Procurement", path: "/policies" });
    expect(await screen.findByRole("link", { name: draft.version })).toBeTruthy();
  });

  it("only Procurement sees the policy screens", () => {
    mockFetch({ "GET /api/workspace/runs": [], "GET /api/workspace": { run: null, requirements: [], not_processed: [], plants: [], routes: [] } });
    renderApp({ role: "Buyer", path: "/workspace" });
    expect(screen.queryByRole("link", { name: "Policy" })).toBeNull();
  });

  it("describing a change starts a draft and opens it", async () => {
    const fetch = mockFetch({ "GET /api/policies": policies, "POST /api/policies/drafts": { ...draft, drafting_status: "drafting" },
      [`GET ${D}`]: { ...draft, drafting_status: "drafting" } });
    renderApp({ role: "Procurement", path: "/policies" });
    fireEvent.change(await screen.findByLabelText("or describe it"), { target: { value: "Spot limit at or below 1.5 lakh from 1 Dec" } });
    fireEvent.click(screen.getByRole("button", { name: "Draft with AI" }));
    expect(await screen.findByText(/The AI is drafting this amendment/)).toBeTruthy();
    expect(JSON.parse(fetch.calls.find((c) => c.method === "POST").body)).toEqual({ text: "Spot limit at or below 1.5 lakh from 1 Dec" });
  });

  it("a failed draft shows the reason and the manual path", async () => {
    mockFetch({ [`GET ${D}`]: { ...draft, drafting_status: "failed", document: null,
      drafting_error: "The AI drafting service is unavailable right now. Start from the current version and edit it by hand instead." } });
    renderApp({ role: "Procurement", path: D.replace("/api", "") });
    expect((await screen.findByRole("alert")).textContent).toMatch(/unavailable right now/);
    expect(screen.getByRole("button", { name: "Edit the current version by hand" })).toBeTruthy();
  });

  it("a ready draft shows what could not be expressed, the changes, and previews the impact", async () => {
    mockFetch({ [`GET ${D}`]: { ...draft, not_expressed: ["The plant head is told by email."] }, "GET /api/runs": runs,
      [`POST ${D.replace("/api/policies/", "/api/policies/drafts/")}/preview`]: preview });
    renderApp({ role: "Procurement", path: D.replace("/api", "") });
    const box = await screen.findByRole("region", { name: "Not expressed" });
    expect(within(box).getByText("The plant head is told by email.")).toBeTruthy();
    for (const line of draft.diff) expect(screen.getByText(line)).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: "Preview the impact" }));
    expect(await screen.findByText(preview.explanation)).toBeTruthy();
  });

  it("approve asks for confirmation and Escape cancels it", async () => {
    const fetch = mockFetch({ [`GET ${D}`]: draft, "GET /api/runs": emptyRuns });
    renderApp({ role: "Procurement", path: D.replace("/api", "") });
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect(screen.getByRole("dialog", { name: `Approve version ${draft.version}?` })).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(fetch.calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("the JSON editor refuses unreadable JSON without saving", async () => {
    const fetch = mockFetch({ [`GET ${D}`]: draft, "GET /api/runs": emptyRuns });
    renderApp({ role: "Procurement", path: D.replace("/api", "") });
    fireEvent.change(await screen.findByLabelText("Policy JSON"), { target: { value: "{oops" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and re-check" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/could not be read.*Nothing was saved/));
    expect(fetch.calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("an approved version shows no approve button, and v5.0 cannot be withdrawn here", async () => {
    mockFetch({ "GET /api/policies/1": approved });
    renderApp({ role: "Procurement", path: "/policies/1" });
    expect(await screen.findByText(/Policy version 5.0/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Withdraw/ })).toBeNull(); // the baseline has no base version
  });
});
