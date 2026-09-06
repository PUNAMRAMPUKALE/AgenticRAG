import { User, UserManager, WebStorageStateStore } from "oidc-client-ts";

export type AuthConfig = {
  issuer: string;
  client_id: string;
  audience: string;
};

export type Me = {
  sub: string;
  username: string;
  roles: string[];
};

export function createUserManager(cfg: AuthConfig): UserManager {
  return new UserManager({
    authority: cfg.issuer,
    client_id: cfg.client_id,
    redirect_uri: `${window.location.origin}/`,
    post_logout_redirect_uri: `${window.location.origin}/`,
    response_type: "code",
    scope: "openid profile email",
    automaticSilentRenew: true,
    loadUserInfo: false,
    extraQueryParams: { audience: cfg.audience },
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  });
}

export async function loadAuthConfig(): Promise<AuthConfig> {
  const fromEnv: AuthConfig = {
    issuer: import.meta.env.VITE_OIDC_AUTHORITY || "http://127.0.0.1:8080/realms/agenticrag",
    client_id: import.meta.env.VITE_OIDC_CLIENT_ID || "agenticrag-spa",
    audience: import.meta.env.VITE_OIDC_AUDIENCE || "agenticrag-api",
  };
  try {
    const res = await fetch("/v1/auth/config");
    if (!res.ok) return fromEnv;
    return (await res.json()) as AuthConfig;
  } catch {
    return fromEnv;
  }
}

export async function completeSignInIfNeeded(mgr: UserManager): Promise<User | null> {
  const params = new URLSearchParams(window.location.search);
  if (params.has("code") && params.has("state")) {
    const user = await mgr.signinRedirectCallback();
    window.history.replaceState({}, document.title, window.location.pathname);
    return user;
  }
  return mgr.getUser();
}

export async function fetchMe(accessToken: string): Promise<Me> {
  const res = await fetch("/v1/auth/me", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) {
    throw new Error(`Session rejected (${res.status})`);
  }
  return (await res.json()) as Me;
}
