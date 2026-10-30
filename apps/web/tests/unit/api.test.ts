import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "@/lib/api";

type Call = { url: string; init: RequestInit };
let calls: Call[];

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
}

beforeEach(async () => {
  await new Promise((r) => setTimeout(r, 0)); // let the shared refresh promise from a previous test reset
  calls = [];
  document.cookie = "dr_csrf=csrf-token-1; path=/";
});
afterEach(() => vi.unstubAllGlobals());

function stubFetch(handler: (url: string, init: RequestInit) => Response | Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ url, init });
    return handler(url, init);
  }));
}

describe("api client", () => {
  it("sends the CSRF header on unsafe methods only", async () => {
    stubFetch(() => json(200, { ok: true }));
    await api("/api/v1/research", { json: { q: 1 } });
    await api("/api/v1/research");
    expect(new Headers(calls[0]!.init.headers).get("x-csrf-token")).toBe("csrf-token-1");
    expect(calls[0]!.init.method).toBe("POST");
    expect(new Headers(calls[1]!.init.headers).get("x-csrf-token")).toBeNull();
  });

  it("maps the API error envelope including the reference ID", async () => {
    stubFetch(() => json(429, { error: { code: "rate_limited", message: "Slow down.", reference_id: "ref123", details: {} } }));
    const err = await api("/api/v1/research").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 429, code: "rate_limited", message: "Slow down.", referenceId: "ref123" });
  });

  it("refreshes the session once on 401 and retries", async () => {
    let n = 0;
    stubFetch((url) => {
      if (url.endsWith("/auth/refresh")) return json(200, { status: "refreshed" });
      n += 1;
      return n === 1 ? json(401, { error: { code: "not_authenticated", message: "x" } }) : json(200, { items: [] });
    });
    await expect(api("/api/v1/research")).resolves.toEqual({ items: [] });
    expect(calls.map((c) => c.url)).toEqual(["/api/v1/research", "/api/v1/auth/refresh", "/api/v1/research"]);
  });

  it("does not loop when refresh fails", async () => {
    stubFetch((url) => (url.endsWith("/auth/refresh") ? json(401, {}) : json(401, { error: { code: "not_authenticated", message: "Sign in" } })));
    await expect(api("/api/v1/research")).rejects.toMatchObject({ status: 401 });
    expect(calls.filter((c) => c.url === "/api/v1/research")).toHaveLength(1);
  });

  it("reports network failures with an actionable message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(api("/api/v1/research")).rejects.toMatchObject({ status: 0, code: "network_error" });
  });
});

describe("fieldErrors", () => {
  it("maps FastAPI validation locations to form fields", async () => {
    const { fieldErrors } = await import("@/lib/api");
    const e = new ApiError(422, { error: { code: "validation_error", message: "Some fields are invalid.", reference_id: "r",
      details: { errors: [{ loc: ["body", "email"], msg: "value is not a valid email address", type: "value_error" }] } } });
    expect(fieldErrors(e)).toEqual({ email: "value is not a valid email address" });
    expect(fieldErrors(new Error("x"))).toEqual({});
  });
});
