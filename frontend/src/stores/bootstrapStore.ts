import { create } from "zustand";
import { fetchBootstrap } from "@/api/stages";
import type { Bootstrap } from "@/types";

interface BootstrapState {
  bootstrap: Bootstrap | null;
  loaded: boolean;
  load: () => Promise<void>;
  apply: (bootstrap: Bootstrap) => void;
  reset: () => void;
}

export const useBootstrapStore = create<BootstrapState>((set) => ({
  bootstrap: null,
  loaded: false,
  load: async () => {
    try {
      const bootstrap = await fetchBootstrap();
      set({ bootstrap, loaded: true });
    } catch {
      set({ loaded: true });
    }
  },
  apply: (bootstrap) => set({ bootstrap, loaded: true }),
  reset: () => set({ bootstrap: null, loaded: false }),
}));
