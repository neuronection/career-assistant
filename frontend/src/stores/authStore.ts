import { create } from "zustand";
import * as authApi from "@/api/auth";
import { TOKEN_KEY } from "@/api/client";
import { useProfileStore } from "@/stores/profileStore";
import { useChatStore } from "@/stores/chatStore";

interface AuthState {
  token: string | null;
  user: authApi.User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName?: string) => Promise<void>;
  loadUser: () => Promise<void>;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem(TOKEN_KEY),
  user: null,
  loading: false,

  login: async (email, password) => {
    set({ loading: true });
    try {
      await authApi.login(email, password);
      await authApi.fetchMe().then((user) => set({ user, token: localStorage.getItem(TOKEN_KEY) }));
    } finally {
      set({ loading: false });
    }
  },

  register: async (email, password, fullName = "") => {
    set({ loading: true });
    try {
      await authApi.register(email, password, fullName);
      await authApi.fetchMe().then((user) => set({ user, token: localStorage.getItem(TOKEN_KEY) }));
    } finally {
      set({ loading: false });
    }
  },

  loadUser: async () => {
    if (!localStorage.getItem(TOKEN_KEY)) return;
    try {
      const user = await authApi.fetchMe();
      set({ user });
    } catch {
      authApi.logout();
      set({ token: null, user: null });
    }
  },

  logout: () => {
    authApi.logout();
    useProfileStore.setState({ profile: null, loading: false });
    useChatStore.setState({ sessions: [], activeSessionId: null, messages: [] });
    set({ token: null, user: null });
  },
}));
