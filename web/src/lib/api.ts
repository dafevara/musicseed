const API_BASE = "/api";
const CSRF_HEADER = "X-MusicSeed-CSRF";

let csrfToken: string | null = null;

async function errorMessage(res: Response): Promise<string> {
  const body = await res.text();
  if (!body) return `${res.status} ${res.statusText}`;
  try {
    const parsed = JSON.parse(body);
    if (parsed && typeof parsed.detail === "string" && parsed.detail) {
      return parsed.detail;
    }
  } catch { /* not JSON */ }
  return body;
}

async function getCsrfToken(): Promise<string> {
  if (csrfToken) return csrfToken;
  const res = await fetch(`${API_BASE}/security/csrf`);
  if (!res.ok) throw new Error(await errorMessage(res));
  const body = await res.json();
  csrfToken = String(body.token);
  return csrfToken;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    throw new Error(await errorMessage(res));
  }
  return res.json();
}

async function mutate<T>(path: string, init: RequestInit): Promise<T> {
  const send = async (): Promise<Response> => {
    const headers: Record<string, string> = {
      ...(init.headers as Record<string, string> | undefined),
    };
    headers[CSRF_HEADER] = await getCsrfToken();
    return fetch(`${API_BASE}${path}`, { ...init, headers });
  };

  let res = await send();
  if (res.status === 403) {
    // The token may predate an API restart; refetch once and retry.
    csrfToken = null;
    res = await send();
  }
  if (!res.ok) {
    throw new Error(await errorMessage(res));
  }
  return res.json();
}

export const api = {
  get<T>(path: string): Promise<T> {
    return request<T>(path);
  },

  post<T>(path: string, body?: Record<string, string | number>): Promise<T> {
    const formBody = new URLSearchParams();
    if (body) {
      for (const [k, v] of Object.entries(body)) {
        formBody.append(k, String(v));
      }
    }
    return mutate<T>(path, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: formBody.toString(),
    });
  },

  delete<T>(path: string): Promise<T> {
    return mutate<T>(path, { method: "DELETE" });
  },
};
