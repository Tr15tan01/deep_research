// Browser API client. All calls go to the same-origin /api proxy (which forwards to FastAPI),
// so session cookies stay HttpOnly and first-party. No tokens are ever stored in JS storage.

import type { ApiErrorBody } from "./types";

export class ApiError extends Error {
  status: number;
  code: string;
  referenceId?: string;
  details: Record<string, unknown>;

  constructor(status: number, body: Partial<ApiErrorBody> | null, fallback = "Request failed.") {
    super(body?.error?.message ?? fallback);
    this.status = status;
    this.code = body?.error?.code ?? (status === 0 ? "network_error" : "http_error");
    this.referenceId = body?.error?.reference_id;
    this.details = body?.error?.details ?? {};
  }
}

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(new RegExp("(?:^|; )" + name.replace(/[.$?*|{}()[\]\\/+^]/g, "\\$&") + "=([^;]*)"));
  return m ? decodeURIComponent(m[1] ?? "") : null;
}

let csrfPromise: Promise<string> | null = null;
async function csrfToken(): Promise<string> {
  const existing = readCookie("dr_csrf");
  if (existing) return existing;
  csrfPromise ??= fetch("/api/v1/auth/csrf", { credentials: "same-origin" })
    .then((r) => r.json())
    .then((d: { csrf_token: string }) => d.csrf_token)
    .finally(() => {
      csrfPromise = null;
    });
  return csrfPromise;
}

let refreshPromise: Promise<boolean> | null = null;
export async function refreshSession(): Promise<boolean> {
  refreshPromise ??= (async () => {
    try {
      const token = await csrfToken();
      const r = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        credentials: "same-origin",
        headers: { "x-csrf-token": token },
      });
      return r.ok;
    } catch {
      return false;
    } finally {
      setTimeout(() => (refreshPromise = null), 0);
    }
  })();
  return refreshPromise;
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  json?: unknown;
  body?: BodyInit;
  retryOn401?: boolean;
}

export async function api<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { json, retryOn401 = true, headers, ...rest } = opts;
  const method = (rest.method ?? (json !== undefined ? "POST" : "GET")).toUpperCase();
  const h = new Headers(headers);
  if (json !== undefined) h.set("content-type", "application/json");
  if (UNSAFE.has(method)) h.set("x-csrf-token", await csrfToken());
  let res: Response;
  try {
    res = await fetch(path.startsWith("/") ? path : `/api/v1/${path}`, {
      ...rest,
      method,
      headers: h,
      credentials: "same-origin",
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch {
    throw new ApiError(0, null, "Can't reach the server. Check your connection and try again.");
  }
  if (res.status === 401 && retryOn401 && !path.includes("/auth/refresh") && !path.includes("/auth/login")) {
    if (await refreshSession()) return api<T>(path, { ...opts, retryOn401: false });
  }
  if (res.status === 403 && retryOn401) {
    // A rotated CSRF cookie (after sign-in) can race an in-flight request; retry once.
    const body = (await res.clone().json().catch(() => null)) as ApiErrorBody | null;
    if (body?.error?.code === "csrf_failed") return api<T>(path, { ...opts, retryOn401: false });
  }
  const ctype = res.headers.get("content-type") ?? "";
  if (!res.ok) {
    const body = ctype.includes("json") ? ((await res.json().catch(() => null)) as ApiErrorBody | null) : null;
    throw new ApiError(res.status, body);
  }
  if (res.status === 204) return undefined as T;
  if (ctype.includes("json")) return (await res.json()) as T;
  return (await res.text()) as T;
}

/** Map a 422 validation envelope to {field: message} so forms can show errors next to the right input. */
export function fieldErrors(e: unknown): Record<string, string> {
  if (!(e instanceof ApiError) || e.code !== "validation_error") return {};
  const errs = (e.details.errors as { loc?: string[]; msg?: string }[] | undefined) ?? [];
  const out: Record<string, string> = {};
  for (const err of errs) {
    const field = err.loc?.[err.loc.length - 1];
    if (field && !out[field]) out[field] = (err.msg ?? "Invalid value.").replace(/^Value error, /, "");
  }
  return out;
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "Something went wrong.";
}

export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const res = await fetch(path, { credentials: "same-origin" });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as ApiErrorBody | null;
    throw new ApiError(res.status, body);
  }
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(cd)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
