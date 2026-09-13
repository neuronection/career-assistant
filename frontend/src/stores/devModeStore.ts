import { create } from "zustand";

const STORAGE_KEY = "career.dev-mode";

const UNLOCK_TAPS = 5;
const TAP_WINDOW_MS = 2000;

interface DevModeState {
  /** Whether in-dev pages are visible in navigation. */
  enabled: boolean;
  /**
   * Count of taps inside the current unlock window; 0 when the window
   * expired. Internal — UI only calls `tap()` / `disable()`.
   */
  taps: number;
  tapWindowStart: number | null;
  /** Multi-tap unlock (e.g. 5 taps within 2s on a hidden trigger). */
  tap: () => void;
  disable: () => void;
}

function loadInitial(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function persist(enabled: boolean) {
  try {
    if (enabled) {
      window.localStorage.setItem(STORAGE_KEY, "1");
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // localStorage unavailable (private mode) — session-only dev mode.
  }
}

export const useDevModeStore = create<DevModeState>((set, get) => ({
  enabled: loadInitial(),
  taps: 0,
  tapWindowStart: null,

  tap: () => {
    const now = Date.now();
    const { taps, tapWindowStart } = get();
    const inWindow = tapWindowStart !== null && now - tapWindowStart <= TAP_WINDOW_MS;
    const next = inWindow ? taps + 1 : 1;
    if (next >= UNLOCK_TAPS) {
      persist(true);
      set({ enabled: true, taps: 0, tapWindowStart: null });
      return;
    }
    set({ taps: next, tapWindowStart: inWindow ? tapWindowStart : now });
  },

  disable: () => {
    persist(false);
    set({ enabled: false, taps: 0, tapWindowStart: null });
  },
}));

/** Test helper: reset the store and its persisted flag. */
export function resetDevMode() {
  useDevModeStore.setState({ enabled: false, taps: 0, tapWindowStart: null });
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
