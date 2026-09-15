import { apiFetch } from "./apiClient";
import { clearAccessToken, setAccessToken } from "./auth";

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  actor_id: string;
  tenant_id: string;
  display_name: string;
  email: string;
  roles: string[];
  permissions: string[];
}

export interface MeResponse {
  actor_id: string;
  tenant_id: string;
  tenant_slug: string;
  display_name: string;
  email: string;
  roles: string[];
  permissions: string[];
  jti: string;
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  // Login must not send a stale Authorization header
  clearAccessToken();
  const res = await fetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as
      | { detail?: { message?: string; code?: string } }
      | null;
    throw new Error(body?.detail?.message ?? `Login failed (${res.status})`);
  }
  const data = (await res.json()) as LoginResponse;
  setAccessToken(data.access_token);
  return data;
}

export async function logout(): Promise<void> {
  try {
    await apiFetch("/api/v1/auth/logout", { method: "POST" });
  } finally {
    clearAccessToken();
  }
}

export async function fetchMe(): Promise<MeResponse> {
  return apiFetch<MeResponse>("/api/v1/auth/me");
}
