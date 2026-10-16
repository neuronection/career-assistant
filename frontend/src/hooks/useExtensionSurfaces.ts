import { useEffect } from "react";
import { fetchSurfaceCards, type SurfaceCard } from "@/api/extensions";
import { useExtensionSurfacesStore, USE_SURFACE_NAV } from "@/stores/extensionSurfacesStore";

/**
 * Extension surfaces top-up for the sidebar (plan 32 Phase 4): installed
 * + ENABLED mini-apps contribute one nav row per page surface. Fetched
 * once per shell mount; the registry view drives labels (locale resolved
 * host-side) — no per-repo hardcoding.
 */
export function useExtensionSurfacesNav(): void {
  useEffect(() => {
    if (!USE_SURFACE_NAV) return;
    void useExtensionSurfacesStore
      .getState()
      .hydrate()
      .catch(() => undefined);
  }, []);
}

export type { SurfaceCard };
export { fetchSurfaceCards };
