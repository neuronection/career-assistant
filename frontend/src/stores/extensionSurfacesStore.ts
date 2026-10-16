import { create } from "zustand";
import type { SurfaceCard } from "@/api/extensions";
import { fetchSurfaceCards } from "@/api/extensions";

/**
 * The extension-surface registry view (plan 32 Phase 4 / ADR-0040 D25):
 * installed + ENABLED mini-apps, one fetch per shell mount. The kill
 * switch is server-side data — a disabled install simply drops out of
 * this list and its page route 404s. Modules can opt out via
 * `USE_SURFACE_NAV` (tests/dev toggles).
 */
export const USE_SURFACE_NAV = true;

interface ExtensionSurfacesState {
  cards: SurfaceCard[];
  loaded: boolean;
  hydrate: () => Promise<void>;
  clear: () => void;
}

export const useExtensionSurfacesStore = create<ExtensionSurfacesState>((set) => ({
  cards: [],
  loaded: false,
  hydrate: async () => {
    const cards = await fetchSurfaceCards();
    set({ cards, loaded: true });
  },
  clear: () => set({ cards: [], loaded: false }),
}));
