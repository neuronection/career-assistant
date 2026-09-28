import { create } from "zustand";
import * as profilesApi from "@/api/profiles";
import type { ProfileSummary } from "@/api/profiles";
import {
  getActiveProfile,
  persistActiveProfile,
  setActiveProfile,
} from "@/api/client";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import { useChatStore } from "@/stores/chatStore";
import { useProfileStore } from "@/stores/profileStore";

/** The user's profiles + the active one (identity-auth §5/§6/§12/§15).
 *
 * Switching is data-level UX: it re-binds every API call (`X-Profile-Id`,
 * §15) and drops the per-profile workspace caches — never authentication. */
interface ProfilesState {
  profiles: ProfileSummary[];
  currentId: string | null;
  /** Bumped on every active-profile change — Layout re-mounts the route
   * subtree on it so pages refetch under the new `X-Profile-Id`. */
  epoch: number;
  loading: boolean;
  error: string | null;
  hydrate: () => Promise<void>;
  select: (profile: ProfileSummary) => Promise<void>;
  create: (name: string) => Promise<void>;
  rename: (profile: ProfileSummary, name: string) => Promise<void>;
  setDefault: (profile: ProfileSummary) => Promise<void>;
  remove: (profile: ProfileSummary) => Promise<void>;
  reset: () => void;
}

let hydrating: Promise<void> | null = null;

function resolveCurrent(profiles: ProfileSummary[]): ProfileSummary | null {
  const stored = getActiveProfile();
  return (
    profiles.find((profile) => profile.id === stored) ??
    profiles.find((profile) => profile.is_default) ??
    profiles[0] ??
    null
  );
}

function dropProfileWorkspace() {
  useProfileStore.setState({ profile: null, loading: false });
  useChatStore.setState({ sessions: [], activeSessionId: null, messages: [] });
}

export const useProfilesStore = create<ProfilesState>((set, get) => ({
  profiles: [],
  currentId: null,
  epoch: 0,
  loading: false,
  error: null,

  hydrate: async () => {
    if (hydrating) return hydrating;
    set({ loading: true, error: null });
    hydrating = (async () => {
      try {
        const profiles = await profilesApi.listProfiles();
        const current = resolveCurrent(profiles);
        setActiveProfile(current ? current.id : null);
        persistActiveProfile(current ? current.id : null);
        set({ profiles, currentId: current ? current.id : null });
      } catch {
        set({ error: "profiles-load-failed" });
      } finally {
        set({ loading: false });
        hydrating = null;
      }
    })();
    return hydrating;
  },

  select: async (profile) => {
    setActiveProfile(profile.id);
    persistActiveProfile(profile.id);
    set({ currentId: profile.id, epoch: get().epoch + 1 });
    dropProfileWorkspace();
    void useBootstrapStore.getState().load();
  },

  create: async (name) => {
    set({ error: null });
    try {
      const created = await profilesApi.createProfile(name);
      const profiles = [...get().profiles, created];
      set({ profiles });
      await get().select(created);
    } catch {
      set({ error: "profiles-create-failed" });
    }
  },

  rename: async (profile, name) => {
    set({ error: null });
    try {
      const updated = await profilesApi.patchProfile(profile.id, { name });
      set({
        profiles: get().profiles.map((row) =>
          row.id === updated.id ? updated : row,
        ),
      });
    } catch {
      set({ error: "profiles-rename-failed" });
    }
  },

  setDefault: async (profile) => {
    set({ error: null });
    try {
      await profilesApi.patchProfile(profile.id, { is_default: true });
      set({
        profiles: get().profiles.map((row) => ({
          ...row,
          is_default: row.id === profile.id,
        })),
      });
    } catch {
      set({ error: "profiles-default-failed" });
    }
  },

  remove: async (profile) => {
    set({ error: null });
    const wasCurrent = get().currentId === profile.id;
    try {
      await profilesApi.deleteProfile(profile.id);
      // Refetch: deleting the last profile re-provisions Default (§6).
      await get().hydrate();
      if (wasCurrent) {
        // The active profile went away — the refetch picked a new one
        // (Default fallback); re-mount pages under it.
        set({ epoch: get().epoch + 1 });
      }
    } catch {
      set({ error: "profiles-delete-failed" });
    }
  },

  reset: () => {
    setActiveProfile(null);
    persistActiveProfile(null);
    set({ profiles: [], currentId: null, loading: false, error: null });
  },
}));
