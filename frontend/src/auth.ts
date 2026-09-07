export type Me = {
  sub: string;
  username: string;
  roles: string[];
};

export type AuthConfig = {
  provider: string;
  client_id: string;
};

const creds: RequestInit = { credentials: "include" };

export async function loadAuthConfig(): Promise<AuthConfig> {
  const res = await fetch("/v1/auth/config", creds);
  if (!res.ok) {
    throw new Error("Could not load auth config. Is uvicorn running? The UI proxies /v1 to port 8000.");
  }
  return (await res.json()) as AuthConfig;
}

export async function fetchMe(): Promise<Me | null> {
  const res = await fetch("/v1/auth/me", creds);
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`Session rejected (${res.status})`);
  return (await res.json()) as Me;
}

export async function signInWithGoogleIdToken(idToken: string): Promise<Me> {
  const res = await fetch("/v1/auth/google", {
    ...creds,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id_token: idToken }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `Google sign-in failed (${res.status})`);
  }
  return (await res.json()) as Me;
}

export async function signOut(): Promise<void> {
  await fetch("/v1/auth/logout", { ...creds, method: "POST" });
}

export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(path, { ...creds, ...init });
}
