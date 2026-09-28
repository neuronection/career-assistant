import axios, { type InternalAxiosRequestConfig } from "axios";

export const api = axios.create({ baseURL: "/api/v1" });

/** Fired when a request cannot be authenticated even after a refresh
 * attempt — the auth gate listens and drops back to the login screen. */
export const UNAUTHENTICATED_EVENT = "nx:unauthenticated";

// --- Desktop Identity Mode (identity-auth §11): the per-boot shell secret
// rides `?shell=` in the SPA URL (it also marks the desktop CSP variant)
// and is echoed as `X-Shell-Token` on every API request.
let shellToken: string | null = null;
try {
  const fromUrl = new URLSearchParams(window.location.search).get("shell");
  if (fromUrl) sessionStorage.setItem("nx_shell", fromUrl);
  shellToken = fromUrl ?? sessionStorage.getItem("nx_shell");
} catch {
  shellToken = null;
}

export function hasShellToken(): boolean {
  return shellToken !== null;
}

// --- Profile binding (identity-auth §15): every domain call carries the
// active profile as `X-Profile-Id`; the server refuses (403/400) any
// other profile-scope. Last-used persists per browser (`ca-profile-id`)
// like study's shell — the desktop server-side fallback uses it too.
export const PROFILE_STORAGE_KEY = "ca-profile-id";

let activeProfileId: string | null = null;
try {
  activeProfileId = window.localStorage.getItem(PROFILE_STORAGE_KEY);
} catch {
  activeProfileId = null;
}

/** Bind every subsequent request to this profile (§15). */
export function setActiveProfile(profileId: string | null): void {
  activeProfileId = profileId;
}

export function getActiveProfile(): string | null {
  return activeProfileId;
}

/** Remember the last-used profile across reloads (best-effort). */
export function persistActiveProfile(profileId: string | null): void {
  try {
    if (profileId === null) {
      window.localStorage.removeItem(PROFILE_STORAGE_KEY);
    } else {
      window.localStorage.setItem(PROFILE_STORAGE_KEY, profileId);
    }
  } catch {
    // profile persistence is best-effort; the in-memory switch still works
  }
}

// First-run bootstrap: before any domain call, resolve the active
// profile (remembered id, else the Default one — §6) so `X-Profile-Id`
// always rides along and the server never sees a scope-less domain call.
// Deduplicated; failures fall through (the request fails honestly).
let profilePrime: Promise<void> | null = null;

function ensureActiveProfile(): Promise<void> {
  if (profilePrime === null) {
    profilePrime = api
      .get<{ id: string; is_default: boolean }[]>("/profiles")
      .then(({ data }) => {
        if (activeProfileId !== null || data.length === 0) return;
        const pick =
          data.find((profile) => profile.is_default) ?? data[0];
        activeProfileId = pick.id;
        persistActiveProfile(pick.id);
      })
      .catch(() => undefined)
      .finally(() => {
        profilePrime = null;
      });
  }
  return profilePrime;
}

function cookieValue(name: string): string | null {
  const prefix = `${name}=`;
  const match = document.cookie.split("; ").find((part) => part.startsWith(prefix));
  return match ? decodeURIComponent(match.slice(prefix.length)) : null;
}

/** Identity headers every API request must ride — the §11 shell gate,
 * §15 profile binding and (on non-safe methods) the §10 CSRF
 * double-submit echo. The single source of truth for both the axios
 * interceptor and the raw-fetch streaming paths, so the two transports
 * cannot drift apart. */
export async function apiRequestHeaders(
  url: string,
  method: string,
): Promise<Record<string, string>> {
  // Auth flows, the profiles listing itself and the public instance
  // facts never prime — the latter two would deadlock the prime on its
  // own fetch (or run before login).
  const profileExempt =
    url.startsWith("/auth/") ||
    url.startsWith("/profiles") ||
    url.startsWith("/instance");
  if (activeProfileId === null && !profileExempt) {
    await ensureActiveProfile();
  }
  const headers: Record<string, string> = {};
  if (shellToken !== null) {
    headers["X-Shell-Token"] = shellToken;
  }
  if (activeProfileId !== null) {
    headers["X-Profile-Id"] = activeProfileId;
  }
  if (method !== "GET" && method !== "HEAD" && method !== "OPTIONS") {
    const csrf = cookieValue("nx_csrf");
    if (csrf !== null) {
      headers["X-CSRF-Token"] = csrf;
    }
  }
  return headers;
}

api.interceptors.request.use(async (config: InternalAxiosRequestConfig) => {
  const url = String(config.url ?? "");
  const method = (config.method ?? "get").toUpperCase();
  if (
    method === "POST" &&
    (url.startsWith("/auth/login") || url.startsWith("/auth/register"))
  ) {
    // Bootstrap credentials: clear a stale cookie jar (a dead previous
    // session, or another family app's cookies on this host — cookies
    // ignore ports) so login never trips the backend's CSRF gate on
    // cookies it did not mint (identity-auth §10/§12).
    for (const name of ['nx_access', 'nx_refresh', 'nx_csrf']) {
      document.cookie = `${name}=; Max-Age=0; path=/`;
      document.cookie = `${name}=; Max-Age=0; path=/api/v1/auth`;
    }
    // The `__Host-` name only exists under TLS (§9) and the prefix
    // rules force `Secure` + `Path=/` on ANY write — a bare clear is
    // rejected for "invalid prefix" and the stale cookie survives.
    // It can only be set from a secure context, so gate the same way.
    if (window.isSecureContext) {
      document.cookie = '__Host-nx_access=; Max-Age=0; path=/; Secure';
    }
  }
  const headers = await apiRequestHeaders(url, method);
  for (const [name, value] of Object.entries(headers)) {
    if (!config.headers.has(name)) {
      config.headers.set(name, value);
    }
  }
  return config;
});

let refreshInFlight: Promise<boolean> | null = null;

/** Rotate the refresh cookie once (deduplicated) — true when a new
 * session was established. */
export function tryRefreshSession(): Promise<boolean> {
  if (refreshInFlight === null) {
    refreshInFlight = api
      .post("/auth/refresh")
      .then((response) => response.status < 400)
      .catch(() => false)
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const response = error.response;
    const config = error.config as (InternalAxiosRequestConfig & { retried?: boolean }) | undefined;
    const url = String(config?.url ?? "");
    const isAuthFlow = url.startsWith("/auth/") || url.startsWith("/api/v1/auth/");
    if (!config || response?.status !== 401 || config.retried || isAuthFlow) {
      if (response?.status === 401 && config && !isAuthFlow) {
        window.dispatchEvent(new Event(UNAUTHENTICATED_EVENT));
      }
      return Promise.reject(error);
    }
    // Expired access with a live refresh cookie: rotate + retry once.
    if (await tryRefreshSession()) {
      config.retried = true;
      try {
        return await api.request(config);
      } catch (retryError) {
        window.dispatchEvent(new Event(UNAUTHENTICATED_EVENT));
        return Promise.reject(retryError);
      }
    }
    window.dispatchEvent(new Event(UNAUTHENTICATED_EVENT));
    return Promise.reject(error);
  },
);

export function apiDetail(error: unknown): string {
  if (axios.isAxiosError(error)) {
    return (error.response?.data?.detail as string) ?? error.message;
  }
  return String(error);
}
