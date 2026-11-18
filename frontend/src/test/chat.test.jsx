import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { mockFetch, renderApp } from "./helpers.jsx";

const EMPTY = { lines: [], plant: null, plant_name: null, need_by: null, urgency: "Normal" };
const GLOVES = { line: 1, item_code: "ITM-1048", description: "Nitrile coated gloves", quantity: "200", unit: "PAIR",
  new_item: false, estimated_unit_price: null };

function conv(over = {}) {
  return { id: 7, status: "open", pr_no: null, messages: [{ sender: "assistant", text: "Hello Meera. What do you need?" }],
    pending: null, draft: EMPTY, missing: ["item", "plant", "need-by date"], choices: [], card: null, ...over };
}

const READY = conv({
  messages: [{ sender: "assistant", text: "Hello" }, { sender: "user", text: "need 200 nitrile gloves for Chakan by next Friday" },
    { sender: "assistant", text: "Found ITM-1048 Nitrile coated gloves (bought in PAIR). Here is your request." }],
  pending: "confirm", missing: [],
  draft: { lines: [GLOVES], plant: "CHK1", plant_name: "Chakan plant", need_by: "2026-11-20", urgency: "Normal" },
  card: { lines: [GLOVES], plant: "CHK1", plant_name: "Chakan plant", need_by: "2026-11-20", urgency: "Normal" },
});

describe("chat intake screen (B3)", () => {
  it("starts a conversation and shows what is still missing", async () => {
    mockFetch({ "POST /api/chat/conversations": conv() });
    renderApp({ role: "Requester", path: "/chat" });
    expect(await screen.findByText("Hello Meera. What do you need?")).toBeTruthy();
    expect(screen.getByText("Still needed: item, plant, need-by date.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Create" })).toBeNull(); // nothing to create yet
  });

  it("Enter sends the message once and does nothing else", async () => {
    const fetch = mockFetch({ "POST /api/chat/conversations": conv(), "POST /api/chat/conversations/7/messages": READY });
    renderApp({ role: "Requester", path: "/chat" });
    const box = await screen.findByLabelText("Message");
    fireEvent.change(box, { target: { value: "need 200 nitrile gloves for Chakan by next Friday" } });
    fireEvent.submit(box.closest("form"));
    await screen.findByText(/Found ITM-1048/);
    const sent = fetch.calls.filter((c) => c.path.endsWith("/messages"));
    expect(sent.length).toBe(1);
    expect(JSON.parse(sent[0].body)).toEqual({ text: "need 200 nitrile gloves for Chakan by next Friday" });
    expect(screen.queryByRole("dialog")).toBeNull(); // Enter never opens the Create confirmation
  });

  it("offers candidate items as buttons that send the choice", async () => {
    const choices = [{ label: "ITM-1009 Hex bolt M10x40 GR 8.8 (NOS)", type: "choose", item_code: "ITM-1009" },
      { label: "None of these", type: "describe_again" }];
    const fetch = mockFetch({ "POST /api/chat/conversations": conv({ choices }), "POST /api/chat/conversations/7/messages": conv() });
    renderApp({ role: "Requester", path: "/chat" });
    fireEvent.click(await screen.findByRole("button", { name: "ITM-1009 Hex bolt M10x40 GR 8.8 (NOS)" }));
    await waitFor(() => expect(fetch.calls.some((c) => c.path.endsWith("/messages"))).toBe(true));
    const body = JSON.parse(fetch.calls.find((c) => c.path.endsWith("/messages")).body);
    expect(body.event.type).toBe("choose");
    expect(body.event.item_code).toBe("ITM-1009");
  });

  it("Create asks for confirmation; Escape closes it without creating", async () => {
    const fetch = mockFetch({ "POST /api/chat/conversations": READY });
    renderApp({ role: "Requester", path: "/chat" });
    fireEvent.click(await screen.findByRole("button", { name: "Create" }));
    expect(screen.getByRole("dialog", { name: "Create this request?" })).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(fetch.calls.filter((c) => c.path.endsWith("/messages")).length).toBe(0);
  });

  it("confirming creates the request and shows what happens next", async () => {
    const created = conv({ status: "created", pr_no: "PRC-26-00001",
      messages: [...READY.messages, { sender: "assistant", text: "Created PRC-26-00001. This is requirement R-0001 and will be placed as a spot PO." }] });
    const fetch = mockFetch({ "POST /api/chat/conversations": READY, "POST /api/chat/conversations/7/messages": created });
    renderApp({ role: "Requester", path: "/chat" });
    fireEvent.click(await screen.findByRole("button", { name: "Create" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Create" }).at(-1));
    expect(await screen.findByRole("heading", { name: "Created PRC-26-00001" })).toBeTruthy();
    expect(JSON.parse(fetch.calls.at(-1).body)).toEqual({ event: { type: "create", label: "Create" } });
    expect(screen.getByRole("button", { name: "Start another request" })).toBeTruthy();
  });

  it("shows a server error as a plain sentence", async () => {
    mockFetch({ "POST /api/chat/conversations": { status: 403, body: { detail: "This needs the Requester or Procurement role." } } });
    renderApp({ role: "Requester", path: "/chat" });
    expect((await screen.findByRole("alert")).textContent).toBe("This needs the Requester or Procurement role.");
  });

  it("My requests lists PRs with their status, and says so when there are none", async () => {
    mockFetch({ "GET /api/chat/requests": [{ pr_no: "PRC-26-00001", plant: "CHK1", need_by: "2026-11-20", urgency: "Normal",
      lines: [{ line: "1", item_code: "ITM-1048", description: "Nitrile coated gloves", quantity: "200.000", unit: "PAIR",
        status: "Waiting for a buyer", route: "SPOT_PO", group_id: "R-0001" }] }] });
    renderApp({ role: "Requester", path: "/requests" });
    expect(await screen.findByText("Waiting for a buyer")).toBeTruthy();
    expect(screen.getByText("spot PO")).toBeTruthy();
  });

  it("a requester sees only the requester screens", () => {
    mockFetch({ "POST /api/chat/conversations": conv() });
    renderApp({ role: "Requester", path: "/chat" });
    const tabs = screen.getAllByRole("link").map((a) => a.textContent);
    expect(tabs).toEqual(["New request", "My requests"]);
  });
});
