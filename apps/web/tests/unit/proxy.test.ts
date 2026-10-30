// @vitest-environment node
// The API proxy must never let a browser smuggle the internal token or a fake client IP to the API.
import { afterEach, describe, expect, it, vi } from "vitest";

import { clientIpFrom } from "@/lib/proxy";

describe("clientIpFrom", () => {
  it("takes the entry appended by the trusted proxy, ignoring client-supplied ones", () => {
    expect(clientIpFrom("6.6.6.6, 203.0.113.7", 1)).toBe("203.0.113.7");
    expect(clientIpFrom("203.0.113.7", 1)).toBe("203.0.113.7");
    expect(clientIpFrom(null, 1)).toBe("");
    expect(clientIpFrom("1.1.1.1", 0)).toBe("");
  });
});

describe("API proxy route", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  async function forwardedHeaders(env: Record<string, string>, incoming: Record<string, string>) {
    for (const [k, v] of Object.entries(env)) vi.stubEnv(k, v);
    let sent: { url: string; headers: Headers } | undefined;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
      sent = { url, headers: new Headers(init.headers) };
      return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
    }));
    const { NextRequest } = await import("next/server");
    const { GET } = await import("@/app/api/v1/[...path]/route");
    const req = new NextRequest("http://localhost:3000/api/v1/public/config", { headers: incoming });
    const res = await GET(req, { params: Promise.resolve({ path: ["public", "config"] }) });
    expect(res.status).toBe(200);
    return sent!;
  }

  it("adds the shared token and observed client IP, dropping spoofed values", async () => {
    const sent = await forwardedHeaders(
      { INTERNAL_PROXY_TOKEN: "s".repeat(40), API_INTERNAL_URL: "https://deep-research-api.onrender.com" },
      { "x-internal-token": "attacker", "x-dr-client-ip": "6.6.6.6", "x-forwarded-for": "6.6.6.6, 198.51.100.4" },
    );
    expect(sent.url).toBe("https://deep-research-api.onrender.com/api/v1/public/config");
    expect(sent.headers.get("x-internal-token")).toBe("s".repeat(40));
    expect(sent.headers.get("x-dr-client-ip")).toBe("198.51.100.4");
  });

  it("forwards no internal headers when no token is configured, and accepts host:port", async () => {
    const sent = await forwardedHeaders({ INTERNAL_PROXY_TOKEN: "", API_INTERNAL_URL: "deep-research-api:8000" },
      { "x-internal-token": "attacker", "x-dr-client-ip": "6.6.6.6" });
    expect(sent.url).toBe("http://deep-research-api:8000/api/v1/public/config");
    expect(sent.headers.get("x-internal-token")).toBeNull();
    expect(sent.headers.get("x-dr-client-ip")).toBeNull();
  });
});
