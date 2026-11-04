import { create } from "zustand";

import {
  fetchDocumentStatuses,
  type RetrievalDocumentSpace,
  type RetrievalDocumentStatus,
} from "@/api/retrieval";

const STORAGE_KEY = "ca:retrieval-debug";
const MAX_IDS = 50;
const inFlight = new Set<string>();

function readEnabled(): boolean {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw === "1" || raw === "true";
  } catch {
    return false;
  }
}

function persistEnabled(enabled: boolean): void {
  try {
    if (enabled) localStorage.setItem(STORAGE_KEY, "1");
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    undefined;
  }
}

interface RetrievalDebugState {
  enabled: boolean;
  space: RetrievalDocumentSpace | null;
  statuses: Record<string, RetrievalDocumentStatus>;
  loading: boolean;
  error: string | null;
  setEnabled: (enabled: boolean) => void;
  load: (sourceIds: string[]) => Promise<void>;
  clear: () => void;
}

export const useRetrievalDebugStore = create<RetrievalDebugState>((set, get) => ({
  enabled: readEnabled(),
  space: null,
  statuses: {},
  loading: false,
  error: null,

  setEnabled: (enabled) => {
    persistEnabled(enabled);
    if (enabled) {
      set({ enabled });
      return;
    }
    set({ enabled, space: null, statuses: {}, error: null });
  },

  load: async (sourceIds) => {
    if (!get().enabled) return;
    const known = get().statuses;
    const pending = Array.from(new Set(sourceIds.map(String)))
      .filter((id) => !(id in known) && !inFlight.has(id))
      .slice(0, MAX_IDS);
    if (pending.length === 0) return;
    for (const id of pending) inFlight.add(id);
    set({ loading: true, error: null });
    try {
      const response = await fetchDocumentStatuses("posting", pending);
      set((state) => ({
        loading: false,
        space: response.space,
        statuses: {
          ...state.statuses,
          ...Object.fromEntries(response.documents.map((row) => [row.source_id, row])),
        },
      }));
    } catch (error) {
      set({
        loading: false,
        error: error instanceof Error ? error.message : String(error),
      });
    } finally {
      for (const id of pending) inFlight.delete(id);
    }
  },

  clear: () => set({ space: null, statuses: {}, error: null }),
}));
