export class ApiError extends Error {
  status: number;
  detail: string;
  howToFix: string[];
  constructor(status: number, detail: string, howToFix: string[] = []) {
    super(detail);
    this.status = status;
    this.detail = detail;
    this.howToFix = howToFix;
  }
}

function token(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("farmos_token");
}

export function setToken(value: string | null) {
  if (typeof window === "undefined") return;
  if (value) localStorage.setItem("farmos_token", value);
  else localStorage.removeItem("farmos_token");
}

export function getToken() {
  return token();
}

function parseDetail(body: { detail?: unknown }): { detail: string; howToFix: string[] } {
  const raw = body.detail;
  if (typeof raw === "string") return { detail: raw, howToFix: [] };
  if (Array.isArray(raw)) {
    return { detail: raw.map((d: { msg?: string }) => d.msg).join("; "), howToFix: [] };
  }
  if (raw && typeof raw === "object") {
    const obj = raw as { error?: string; message?: string; how_to_fix?: string[] };
    return {
      detail: obj.error || obj.message || "Request failed",
      howToFix: Array.isArray(obj.how_to_fix) ? obj.how_to_fix : [],
    };
  }
  return { detail: "Request failed", howToFix: [] };
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const isForm = typeof FormData !== "undefined" && init.body instanceof FormData;
  if (!isForm && !headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  const t = token();
  if (t) headers.set("Authorization", `Bearer ${t}`);
  const doFetch = typeof window !== "undefined" ? window.fetch.bind(window) : fetch;
  const res = await doFetch(path, {
    ...init,
    headers,
    cache: "no-store",
    signal: init.signal ?? AbortSignal.timeout(20000),
  });
  if (res.status === 401 && typeof window !== "undefined") {
    const here = window.location.pathname;
    if (here !== "/login" && here !== "/setup") {
      setToken(null);
      window.location.href = "/login";
    }
  }
  if (!res.ok) {
    let detail = res.statusText;
    let howToFix: string[] = [];
    try {
      const parsed = parseDetail(await res.json());
      detail = parsed.detail;
      howToFix = parsed.howToFix;
    } catch {
      if (res.status >= 500) {
        detail =
          "The farm API did not respond. Wait 15 seconds and try again, or run: docker compose logs backend";
      }
    }
    throw new ApiError(res.status, detail, howToFix);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export type AuthUser = {
  access_token: string;
  role: string;
  email: string;
  full_name: string;
};
