// Same-origin backend-for-frontend proxy to the FastAPI service.
//
// Why: session cookies stay HttpOnly and first-party on the frontend origin, the browser never
// talks to the API host directly, and SSE responses are streamed through unbuffered.
// The proxy does not authenticate anything itself — FastAPI authorizes every request.

import type { NextRequest } from "next/server";

import { clientIpFrom } from "@/lib/proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// Accepts a full URL or a bare "host:port" (what Render's `fromService … property: hostport` provides).
const RAW_API = (process.env.API_INTERNAL_URL || process.env.API_URL || "http://localhost:8000").trim().replace(/\/$/, "");
const API = /^https?:\/\//.test(RAW_API) ? RAW_API : `http://${RAW_API}`;
// Single-service hosting (e.g. Render free tier): the API has a public URL and only accepts requests carrying
// this shared secret, which never leaves the server. Clients can never supply these headers themselves.
const INTERNAL_TOKEN = process.env.INTERNAL_PROXY_TOKEN ?? "";
const PROXY_ONLY_HEADERS = new Set(["x-internal-token", "x-dr-client-ip"]);

const HOP_BY_HOP = new Set(["connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
  "transfer-encoding", "upgrade", "host", "content-length", "accept-encoding"]);
const MAX_BODY = 25 * 1024 * 1024;

async function forward(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const { path } = await ctx.params;
  if (path.some((p) => p === ".." || p.includes("\\"))) return new Response("Bad path", { status: 400 });
  const target = `${API}/api/v1/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers = new Headers();
  req.headers.forEach((v, k) => {
    const key = k.toLowerCase();
    if (!HOP_BY_HOP.has(key) && !PROXY_ONLY_HEADERS.has(key)) headers.set(k, v);
  });
  if (INTERNAL_TOKEN) {
    headers.set("x-internal-token", INTERNAL_TOKEN);
    const ip = clientIpFrom(req.headers.get("x-forwarded-for"));
    if (ip) headers.set("x-dr-client-ip", ip);
  }
  // Origin of the browser request is preserved for the API's CSRF origin check.
  let body: ArrayBuffer | undefined;
  if (!["GET", "HEAD"].includes(req.method)) {
    const len = Number(req.headers.get("content-length") || "0");
    if (len > MAX_BODY) return Response.json({ error: { code: "payload_too_large", message: "Request is too large.", reference_id: "", details: {} } }, { status: 413 });
    body = await req.arrayBuffer();
  }
  let upstream: Response;
  try {
    upstream = await fetch(target, { method: req.method, headers, body, redirect: "manual", cache: "no-store",
      signal: req.signal });
  } catch {
    return Response.json(
      { error: { code: "api_unreachable", message: "The research service is unreachable. Please try again shortly.", reference_id: "", details: {} } },
      { status: 503 },
    );
  }
  const out = new Headers();
  upstream.headers.forEach((v, k) => {
    if (!HOP_BY_HOP.has(k.toLowerCase()) && k.toLowerCase() !== "set-cookie" && k.toLowerCase() !== "content-encoding") out.set(k, v);
  });
  for (const c of upstream.headers.getSetCookie()) out.append("set-cookie", c);
  if ((upstream.headers.get("content-type") || "").includes("text/event-stream")) {
    out.set("cache-control", "no-cache, no-transform");
    out.set("x-accel-buffering", "no");
  }
  return new Response(upstream.body, { status: upstream.status, statusText: upstream.statusText, headers: out });
}

export { forward as GET, forward as POST, forward as PUT, forward as PATCH, forward as DELETE };
