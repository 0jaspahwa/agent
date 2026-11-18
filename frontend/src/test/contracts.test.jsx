import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import emptyContracts from "./fixtures/empty/contracts.json";
import contracts from "./fixtures/sample/contracts.json";
import items from "./fixtures/sample/items.json";
import suppliers from "./fixtures/sample/suppliers.json";
import { mockFetch, renderApp } from "./helpers.jsx";

const PDF_031 = contracts.find((c) => c.contract_id === "RC-2026-031");
const FORM = { ...PDF_031, read_by: "pdf reader", needs_checking: false };

function base(extra = {}) {
  return mockFetch({ "GET /api/contracts": contracts, "GET /api/items": items, "GET /api/suppliers": suppliers, ...extra });
}

function choosePdf() {
  const file = new File(["%PDF"], "RC-2026-031.pdf", { type: "application/pdf" });
  fireEvent.change(screen.getByLabelText("Signed contract PDF"), { target: { files: [file] } });
  fireEvent.click(screen.getByRole("button", { name: "Read the PDF" }));
}

describe("contracts screen (B6)", () => {
  it("renders on an empty database and on the sample data", async () => {
    mockFetch({ "GET /api/contracts": emptyContracts });
    const { unmount } = renderApp({ role: "Buyer", path: "/contracts" });
    expect(await screen.findByRole("heading", { name: "Contracts" })).toBeTruthy();
    unmount();
    base();
    renderApp({ role: "Buyer", path: "/contracts" });
    expect(await screen.findByText("RC-2026-031")).toBeTruthy();
    const table = screen.getAllByRole("table")[0];
    expect(within(table).getAllByRole("row").length - 1).toBe(contracts.length);
  });

  it("reading a PDF fills the form, and saving asks for confirmation", async () => {
    const fetch = base({ "POST /api/contracts/read-pdf": { form: FORM }, "POST /api/contracts": { ...PDF_031, warnings: [] } });
    renderApp({ role: "Buyer", path: "/contracts" });
    await screen.findByText("RC-2026-033");
    choosePdf();
    expect(await screen.findByText(/Read from the PDF by the deterministic reader/)).toBeTruthy();
    expect(screen.getByLabelText("Contract number").value).toBe("RC-2026-031");
    fireEvent.click(screen.getByRole("button", { name: "Save contract" }));
    const dialog = screen.getByRole("dialog");
    expect(fetch.calls.some((c) => c.method === "POST" && c.path === "/api/contracts")).toBe(false); // not before confirming
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Saved RC-2026-031/)).toBeTruthy();
    const body = JSON.parse(fetch.calls.find((c) => c.method === "POST" && c.path === "/api/contracts").body);
    expect(body.source).toBe("pdf");
    expect(body.form.contract_id).toBe("RC-2026-031");
  });

  it("when the reader cannot read the file it says why and offers the AI or the form by hand", async () => {
    base({ "POST /api/contracts/read-pdf": { error: "x.pdf: expected exactly one contract number, found 0", llm_available: true } });
    renderApp({ role: "Buyer", path: "/contracts" });
    await screen.findByText("RC-2026-033");
    choosePdf();
    expect((await screen.findByRole("alert")).textContent).toMatch(/expected exactly one contract number/);
    expect(screen.getByRole("button", { name: /Ask the AI to read it/ })).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Fill in by hand" }).at(-1));
    expect(screen.getByLabelText("Contract number").value).toBe("");
  });

  it("an AI reading is marked as needing checking", async () => {
    base({ "POST /api/contracts/read-pdf": { form: { ...FORM, read_by: "AI (gemini:x)", needs_checking: true } } });
    renderApp({ role: "Buyer", path: "/contracts" });
    await screen.findByText("RC-2026-033");
    choosePdf();
    expect(await screen.findByText(/Check every field against the PDF before saving/)).toBeTruthy();
  });

  it("the server's problems are shown as plain sentences", async () => {
    base({ "POST /api/contracts": { status: 422, body: { detail: "The contract cannot be saved: Contract RC-2026-031 already exists.", problems: [] } } });
    renderApp({ role: "Buyer", path: "/contracts" });
    fireEvent.click((await screen.findAllByRole("button", { name: "Fill in by hand" }))[0]);
    fireEvent.change(screen.getByLabelText("Contract number"), { target: { value: "RC-2026-031" } });
    fireEvent.submit(screen.getByLabelText("Contract number").closest("form"));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/already exists/));
  });
});
