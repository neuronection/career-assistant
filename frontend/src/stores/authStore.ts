import { create } from "zustand";
import * as authApi from "@/api/auth";
import { api, tryRefreshSession } from "@/api/client";
import { useProfileStore } from "@/stores/profileStore";
import { useProfilesStore } from "@/stores/profilesStore";
import { useChatStore } from "@/stores/chatStore";

export type AuthStatus = "checking" | "authenticated" | "anonymous";

/** Result of a register attempt — `"disabled"` when the instance runs
 * with `REGISTRATION_ENABLED=false` (§12 answers 403): the login screen
 * drops its register action instead of showing a generic failure. */
export type RegisterOutcome = "ok" | "disabled" | "failed";

interface AuthState {
  user: authApi.User | null;
  loading: boolean;
  status: AuthStatus;
  error: string | null;
  loadUser: () => Promise<boolean>;
  boot: () => Promise<boolean>;
  login: (email: string, password: string) => Promise<boolean>;
  register: (
    email: string,
    password: string,
    fullName?: string,
  ) => Promise<RegisterOutcome>;
  logout: () => Promise<void>;
  dropToLogin: () => void;
  reset: () => void;
}

function clearWorkspace() {
  useProfileStore.setState({ profile: null, loading: false });
  useProfilesStore.getState().reset();
  useChatStore.setState({ sessions: [], activeSessionId: null, messages: [] });
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  loading: false,
  status: "checking",
  error: null,

  loadUser: async () => {
    set({ loading: true, error: null });
    try {
      const user = await authApi.fetchMe();
      set({ user, loading: false, status: "authenticated" });
      return true;
    } catch {
      set({ user: null, loading: false, error: "not-authenticated", status: "anonymous" });
      return false;
    }
  },

  /** Establish a session before the app renders (identity-auth §4/§11):
   * 1. live session cookie → done; 2. expired access + valid refresh →
   * rotate, re-check; 3. desktop entrypoint (`?shell=`) → one-time DIM
   * exchange (zero setup); 4. otherwise anonymous → the login gate. */
  boot: async () => {
    set({ status: "checking" });
    if (await get().loadUser()) return true;
    if (await tryRefreshSession()) {
      if (await get().loadUser()) return true;
    }
    // Desktop DIM boot exchange: the shipped shell (?shell=) or the
    // shell-less dev server (gate disarmed, ADR-0023) mints the implicit
    // owner. The route is unmounted on server deployments (404) and 404s
    // on authenticated desktop instances — both fall to the login gate.
    try {
      await api.post("/auth/desktop/exchange");
      if (await get().loadUser()) return true;
    } catch {
      // no DIM here — fall through to the login gate
    }
    set({ user: null, status: "anonymous", error: "not-authenticated" });
    return false;
  },

  login: async (email, password) => {
    set({ loading: true, error: null });
    try {
      const user = await authApi.login({ email, password });
      set({ user, loading: false, status: "authenticated" });
      return true;
    } catch {
      set({ loading: false, error: "login-failed" });
      return false;
    }
  },

  register: async (email, password, fullName = "") => {
    set({ loading: true, error: null });
    try {
      const user = await authApi.register({ email, password, full_name: fullName });
      set({ user, loading: false, status: "authenticated" });
      return "ok";
    } catch (error) {
      set({ loading: false, error: "register-failed" });
      return authApi.isRegistrationDisabled(error) ? "disabled" : "failed";
    }
  },

  logout: async () => {
    try {
      await authApi.logout();
    } finally {
      clearWorkspace();
      set({ user: null, status: "anonymous", error: null, loading: false });
    }
  },

  /** Drop straight to the login screen without an API round-trip — for
   * self-service flows where the session is already gone server-side
   * (revoking the current device, deleting the account). A no-op while
   * the boot machine is still running: a background-401 racing the DIM
   * exchange (e.g. a pre-auth hydrate) must not wedge the gate on a
   * stale anonymous verdict — the boot itself lands the session. */
  dropToLogin: () => {
    if (get().status === "checking") return;
    clearWorkspace();
    set({ user: null, status: "anonymous", error: null, loading: false });
  },

  reset: () => {
    clearWorkspace();
    set({ user: null });
  },
}));
