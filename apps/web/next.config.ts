import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV !== "production";

// CSP: Next's runtime injects inline scripts/styles; a nonce-based policy would force dynamic
// rendering of every page. We allow 'unsafe-inline' for scripts/styles but keep everything else
// locked to our own origin (all API traffic goes through the same-origin /api proxy).
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self' https://accounts.google.com",
  "object-src 'none'",
].join("; ");

const nextConfig: NextConfig = {
  // Self-contained server bundle for the Docker image (set in infra/docker/web.Dockerfile). Hosts that run
  // `next start` directly (e.g. Render's Node runtime) use the regular build output.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  poweredByHeader: false,
  reactStrictMode: true,
  compress: false, // never buffer/compress the SSE stream in the API proxy; let the edge/CDN compress
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          ...(isDev ? [] : [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" }]),
        ],
      },
    ];
  },
};

export default nextConfig;
