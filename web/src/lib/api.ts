const API_BASE = "/api";

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
    return request<T>(path, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: formBody.toString(),
    });
  },

  delete<T>(path: string): Promise<T> {
    return request<T>(path, { method: "DELETE" });
  },
};
