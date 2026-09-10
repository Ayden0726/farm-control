export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
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

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const isForm = typeof FormData !== "undefined" && init.body instanceof FormData;
  if (!isForm && !headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  const t = token();
  if (t) headers.set("Authorization", `Bearer ${t}`);
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401 && typeof window !== "undefined") {
    const here = window.location.pathname;
    if (here !== "/login" && here !== "/setup") {
      setToken(null);
      window.location.href = "/login";
    }
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg?: string }) => d.msg).join("; ");
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
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
