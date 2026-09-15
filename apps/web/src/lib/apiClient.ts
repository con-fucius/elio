import { getAccessToken, getDeviceId } from "./auth";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly correlationId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const token = getAccessToken();
  const headers = new Headers(init.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  headers.set("X-Device-Id", getDeviceId());
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(path, { ...init, headers });
  if (res.status === 204) {
    return undefined as T;
  }

  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { message: text };
    }
  }

  if (!res.ok) {
    const detail = (body as { detail?: Record<string, unknown> } | null)?.detail;
    const code =
      typeof detail?.code === "string" ? detail.code : `HTTP_${res.status}`;
    const message =
      typeof detail?.message === "string"
        ? detail.message
        : `Request failed with ${res.status}`;
    throw new ApiError(res.status, code, message, res.headers.get("X-Correlation-ID") ?? undefined);
  }
  return body as T;
}
