/**
 * Auth token store. Elio API verifies OIDC/JWT; this module only holds and reads
 * the access token the client already obtained. No password login against Elio.
 */

const TOKEN_KEY = "elio.access_token";
const DEVICE_KEY = "elio.device_id";

export function getAccessToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setAccessToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearAccessToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function getDeviceId(): string {
  let id = localStorage.getItem(DEVICE_KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(DEVICE_KEY, id);
  }
  return id;
}
