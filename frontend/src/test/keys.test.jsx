import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import contracts from "./fixtures/sample/contracts.json";
import items from "./fixtures/sample/items.json";
import suppliers from "./fixtures/sample/suppliers.json";
import { mockFetch, renderApp } from "./helpers.jsx";

// S3: keyboard and reload behaviour across forms (docs/break_it.md).
const OPEN = { id: 7, status: "open", pr_no: null, pending: "quantity", missing: ["quantity"], choices: [], card: null,
  messages: [{ sender: "assistant", text: "Hello" }, { sender: "user", text: "need nitrile gloves" },
    { sender: "assistant", text: "How many Nitrile coated gloves (in PAIR) do you need?" }],
  draft: { lines: [{ line: 1, item_code: "ITM-1048", description: "Nitrile coated gloves", quantity: null, unit: "PAIR" }],
    plant: null, plant_name: null, need_by: null, urgency: "Normal" } };

describe("keyboard and reloads (S3)", () => {
  it("Tab and Shift+Tab stay inside an open dialog", async () => {
    mockFetch({ "GET /api/contracts": contracts, "GET /api/items": items, "GET /api/suppliers": suppliers });
    renderApp({ role: "Buyer", path: "/contracts" });
    fireEvent.click((await screen.findAllByRole("button", { name: "Fill in by hand" }))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Save contract" }));
    const dialog = within(screen.getByRole("dialog"));
    const save = dialog.getByRole("button", { name: "Save" });
    const cancel = dialog.getByRole("button", { name: "Cancel" });
    expect(document.activeElement).toBe(save); // focus moved into the dialog
    cancel.focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(document.activeElement).toBe(save); // wrapped from the last to the first
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(cancel); // and back
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("Enter in the contract form opens the confirmation and saves nothing by itself", async () => {
    const fetch = mockFetch({ "GET /api/contracts": contracts, "GET /api/items": items, "GET /api/suppliers": suppliers });
    renderApp({ role: "Buyer", path: "/contracts" });
    fireEvent.click((await screen.findAllByRole("button", { name: "Fill in by hand" }))[0]);
    fireEvent.submit(screen.getByLabelText("Contract number").closest("form"));
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(fetch.calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("a reload in the middle of a chat continues the same conversation", async () => {
    window.sessionStorage.setItem("corvo.chat", "7");
    const fetch = mockFetch({ "GET /api/chat/conversations/7": OPEN, "POST /api/chat/conversations": { ...OPEN, id: 8 } });
    renderApp({ role: "Requester", path: "/chat" });
    expect(await screen.findByText(/How many Nitrile coated gloves/)).toBeTruthy();
    expect(fetch.calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("a finished conversation is not resumed after a reload", async () => {
    window.sessionStorage.setItem("corvo.chat", "7");
    mockFetch({ "GET /api/chat/conversations/7": { ...OPEN, status: "created" },
      "POST /api/chat/conversations": { ...OPEN, id: 8, messages: [{ sender: "assistant", text: "Hello again" }] } });
    renderApp({ role: "Requester", path: "/chat" });
    expect(await screen.findByText("Hello again")).toBeTruthy();
    expect(window.sessionStorage.getItem("corvo.chat")).toBe("8");
  });
});
