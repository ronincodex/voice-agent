import type { ApiResponse, PaginatedResponse } from "./types";

/**
 * Base URL for every API call. The NEXT_PUBLIC_ prefix means the
 * value is inlined at build time and available in both Server
 * Components (which run on the Next.js server) and Client
 * Components (which run in the browser).
 *
 * The fallback to localhost keeps the dev environment usable even
 * if .env.local is missing.
 */
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/**
 * Headers sent on every API request from the browser.
 *
 * ngrok-skip-browser-warning tells the ngrok free-tier proxy to
 * pass the request through instead of serving its "you are about
 * to visit..." interstitial. That interstitial has no CORS
 * headers, so a browser fetch that receives it fails with "No
 * Access-Control-Allow-Origin header is present". Server-side
 * fetches never see the interstitial, which is why dashboard and
 * calls pages have worked while the audio player has not.
 *
 * Harmless against a backend that is not behind ngrok: Render,
 * for example, ignores unknown request headers. When the backend
 * moves to Render in Phase 8, this header can stay — it does no
 * harm — or be removed.
 */
export const BROWSER_HEADERS: HeadersInit = {
  Accept: "application/json",
  "ngrok-skip-browser-warning": "true",
};

/**
 * Error type thrown by fetchApi on any non-2xx response. Carries
 * the HTTP status and FastAPI's `detail` string so call sites can
 * distinguish "not found" from "network down" from "validation
 * failed" without inspecting message text.
 */
export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

/**
 * Fetch a single-object endpoint and unwrap the {success, data}
 * envelope. The caller receives `data` directly.
 *
 * Revalidation: Next.js caches Server Component fetches. The
 * `revalidate: 30` option means the stats are refreshed at most
 * every 30 seconds, which matches how often a real dashboard user
 * would expect the numbers to move.
 */
export async function fetchApi<T>(path: string): Promise<T> {
  const url = `${API_BASE_URL}${path}`;
  const res = await fetch(url, {
    headers: BROWSER_HEADERS,
    next: { revalidate: 30 },
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      // Non-JSON error body; keep the HTTP status text.
    }
    throw new ApiError(res.status, detail);
  }

  const body = (await res.json()) as ApiResponse<T>;
  return body.data;
}

/**
 * Fetch a list endpoint and return the full envelope, including
 * pagination metadata. Session 7.4 uses this for the calls table.
 */
export async function fetchPaginated<T>(
  path: string,
): Promise<PaginatedResponse<T>> {
  const url = `${API_BASE_URL}${path}`;
  const res = await fetch(url, {
    headers: BROWSER_HEADERS,
    next: { revalidate: 30 },
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      // Non-JSON error body.
    }
    throw new ApiError(res.status, detail);
  }

  return (await res.json()) as PaginatedResponse<T>;
}
