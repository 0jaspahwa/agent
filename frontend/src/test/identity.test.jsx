import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { api, plainMessage, setApiIdentity } from "../api.js";
import { mockFetch, renderApp } from "./helpers.jsx";

describe("identity (B1)", () => {
  it("asks for a name and a role first, and Continue needs both", () => {
    renderApp({ role: null });
    const go = screen.getByRole("button", { name: "Continue" });
    expect(go.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Ravi" } });
    expect(go.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/Buyer/));
    expect(go.disabled).toBe(false);
    fireEvent.click(go);
    expect(screen.getByText(/Ravi · Buyer/)).toBeTruthy();
  });

  it("Enter in the name field submits the identity form only when it is complete", () => {
    renderApp({ role: null });
    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Ravi" } });
    fireEvent.submit(screen.getByLabelText("Your name").closest("form"));
    expect(screen.getByRole("button", { name: "Continue" })).toBeTruthy(); // still on the identity screen
  });

  it("Change goes back to the identity screen with the current values", () => {
    renderApp({ role: "Requester", name: "Meera" });
    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(screen.getByLabelText("Your name").value).toBe("Meera");
  });

  it("sends the name and role with every request", async () => {
    const fetch = mockFetch({ "GET /api/health": { status: "ok" } });
    setApiIdentity({ name: "Asha Rao", role: "Procurement" });
    await api("/api/health");
    expect(fetch.calls[0].headers).toEqual({ "X-User": "Asha%20Rao", "X-Role": "Procurement" });
  });

  it("turns server errors into plain sentences", () => {
    expect(plainMessage({ detail: "Only the Procurement role can approve a policy version." }, 403))
      .toBe("Only the Procurement role can approve a policy version.");
    expect(plainMessage("<html>Internal Server Error</html>", 500)).toMatch(/^Something went wrong on the server/);
    expect(plainMessage({ detail: [{ loc: ["body", "quantity"], msg: "must be positive" }] }, 422)).toBe("quantity: must be positive");
  });
});
