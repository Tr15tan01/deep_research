// Feature flags from /public/config drive what the UI offers (the backend enforces the same flags).
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const config = { features: { google_auth: false, google_auth_configured: false } };
vi.mock("@/components/providers", () => ({ useConfig: () => config }));

const { GoogleButton } = await import("@/components/auth-ui");

describe("Google sign-in flag", () => {
  beforeEach(() => {
    config.features.google_auth = false;
    config.features.google_auth_configured = false;
  });

  it("renders nothing when GOOGLE_AUTH_ENABLED=0", () => {
    const { container } = render(<GoogleButton />);
    expect(container).toBeEmptyDOMElement();
  });

  it("explains misconfiguration instead of offering a broken button", () => {
    config.features.google_auth = true;
    render(<GoogleButton />);
    expect(screen.getByText(/enabled but not configured/i)).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("links to the backend OAuth start with a safe next parameter", () => {
    config.features.google_auth = true;
    config.features.google_auth_configured = true;
    render(<GoogleButton next="/research/new" />);
    expect(screen.getByRole("link", { name: /continue with google/i })).toHaveAttribute(
      "href", "/api/v1/auth/google/start?next=%2Fresearch%2Fnew");
  });
});
