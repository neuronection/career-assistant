import { create } from "zustand";

import { getInstanceConfig, type DatastoreQuarantine } from "@/api/instance";

/** Local dismissal key — the notice is client-local, keyed by the
 * quarantine timestamp (no dismissal endpoint; family datastore-breaks
 * contract). */
export const QUARANTINE_SEEN_KEY = "ca.datastore-quarantine-seen";

interface DatastoreQuarantineState {
  /** `null` until the boot check resolves — callers must wait, never assume
   * "no notice", so the first-run wizard never opens on a quarantined boot. */
  pending: boolean | null;
  notice: DatastoreQuarantine | null;
  load: () => Promise<void>;
  dismiss: () => void;
  reset: () => void;
}

let loading: Promise<void> | null = null;

/** The notice is best-effort: a stalled boot check must never hold the app
 * (or the first-run wizard) hostage, so it resolves after this bound. */
const BOOT_CHECK_DEADLINE_MS = 5000;

function readSeen(): string | null {
  try {
    return localStorage.getItem(QUARANTINE_SEEN_KEY);
  } catch {
    return null;
  }
}

async function settleWithin<T>(promise: Promise<T>, ms: number): Promise<T | null> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<null>((resolve) => {
        timer = setTimeout(() => resolve(null), ms);
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

export const useDatastoreQuarantineStore = create<DatastoreQuarantineState>((set, get) => ({
  pending: null,
  notice: null,
  load: async () => {
    if (get().pending !== null) return;
    if (loading) return loading;
    loading = (async () => {
      const config = await settleWithin(getInstanceConfig(), BOOT_CHECK_DEADLINE_MS).catch(
        () => null,
      );
      if (!config) {
        set({ notice: null, pending: false });
        return;
      }
      const quarantine = config.datastore_quarantine ?? null;
      const notice =
        quarantine && readSeen() !== quarantine.quarantined_at ? quarantine : null;
      set({ notice, pending: notice !== null });
    })().finally(() => {
      loading = null;
    });
    return loading;
  },
  dismiss: () => {
    const notice = get().notice;
    if (notice) {
      try {
        localStorage.setItem(QUARANTINE_SEEN_KEY, notice.quarantined_at);
      } catch {
        // A blocked storage still dismisses for this session.
      }
    }
    set({ notice: null, pending: false });
  },
  reset: () => set({ pending: null, notice: null }),
}));
