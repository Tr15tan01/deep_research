// Helpers for the same-origin API proxy (app/api/v1/[...path]/route.ts).

/** Number of reverse proxies in front of this Next.js server that append to X-Forwarded-For (Render: 1). */
export const WEB_PROXY_HOPS = Math.max(0, Number(process.env.WEB_TRUSTED_PROXY_HOPS ?? 1));

/**
 * The client IP as seen by the trusted proxy in front of us: the entry that proxy appended. Anything earlier in the
 * header was supplied by the client and is ignored, so it cannot be spoofed to dodge rate limits.
 */
export function clientIpFrom(xff: string | null, hops = WEB_PROXY_HOPS): string {
  const parts = (xff ?? "").split(",").map((p) => p.trim()).filter(Boolean);
  return hops > 0 && parts.length >= hops ? parts[parts.length - hops]! : "";
}
