import { create } from "zustand";

import type { CvAssistantState } from "@/types/cvAssistant";

/**
 * The link between the ONE chatbot and the CV builder page:
 * the generic chat surfaces forward the copilot's terminal
 * `builder_state` payload here, and the builder page — if mounted —
 * re-syncs its state from it. The builder also registers a pending-save
 * flush so a chat turn never races the editor's debounced autosave.
 * Nothing chat-specific lives here; with no builder mounted the state
 * simply accumulates and is ignored.
 */
interface CvBuilderLinkState {
  lastBuilderState: CvAssistantState | null;
  flushCallback: (() => void) | null;
  applyBuilderState: (state: CvAssistantState) => void;
  registerFlush: (flush: (() => void) | null) => void;
  flushPendingSave: () => void;
}

export const useCvBuilderLink = create<CvBuilderLinkState>((set, get) => ({
  lastBuilderState: null,
  flushCallback: null,
  applyBuilderState: (state) => set({ lastBuilderState: state }),
  registerFlush: (flush) => set({ flushCallback: flush }),
  flushPendingSave: () => {
    const flush = get().flushCallback;
    if (flush) flush();
  },
}));
