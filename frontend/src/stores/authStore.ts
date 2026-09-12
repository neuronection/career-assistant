import { create } from "zustand";
import * as authApi from "@/api/auth";
import { useProfileStore } from "@/stores/profileStore";
import { useChatStore } from "@/stores/chatStore";

interface AuthState {
  user: authApi.User | null;
  loading: boolean;
  error: string | null;
  loadUser: () => Promise<void>;
  reset: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  loading: false,
  error: null,

  loadUser: async () => {
    set({ loading: true, error: null });
    try {
      const user = await authApi.fetchMe();
      set({ user, loading: false });
    } catch {
      set({ user: null, loading: false, error: "not-authenticated" });
    }
  },

  reset: () => {
    useProfileStore.setState({ profile: null, loading: false });
    useChatStore.setState({ sessions: [], activeSessionId: null, messages: [] });
    set({ user: null });
  },
}));
