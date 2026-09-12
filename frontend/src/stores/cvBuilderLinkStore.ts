import { create } from "zustand";

import type { CvAssistantState } from "@/types/cvAssistant";
import type { LiveTurnTraceInput } from "@/lib/cvBuildTrace";

/**
 * The link between the ONE chatbot and the CV builder page:
 * the generic chat surfaces forward the copilot's terminal
 * `builder_state` payload here, and the builder page — if mounted —
 * re-syncs its state from it. The builder also registers a pending-save
 * flush so a chat turn never races the editor's debounced autosave.
 * Nothing chat-specific lives here; with no builder mounted the state
 * simply accumulates and is ignored.
 *
 * Plan 67: the link also mirrors the LIVE turn's flow events
 * (node/tool snapshots from the chat stream reducer) CV-scoped
 * (`cv:${id}` keys) so the builder
 * page shows the copilot's activity even with the chat dock closed.
 * Deltas/text never ride the mirror; they stay in the dock.
 */
interface CvBuilderLinkState {
  lastBuilderState: CvAssistantState | null;
  liveTurns: Record<string, LiveTurnTraceInput>;
  flushCallback: (() => void) | null;
  applyBuilderState: (state: CvAssistantState) => void;
  applyTurnTrace: (cvId: string, trace: LiveTurnTraceInput | null) => void;
  registerFlush: (flush: (() => void) | null) => void;
  flushPendingSave: () => void;
}

function turnKey(cvId: string): string {
  return `cv:${cvId}`;
}

export const useCvBuilderLink = create<CvBuilderLinkState>((set, get) => ({
  lastBuilderState: null,
  liveTurns: {},
  flushCallback: null,
  applyBuilderState: (state) => set({ lastBuilderState: state }),
  applyTurnTrace: (cvId, trace) => {
    const key = turnKey(cvId);
    if (trace === null) {
      if (get().liveTurns[key] === undefined) return;
      const liveTurns = { ...get().liveTurns };
      delete liveTurns[key];
      set({ liveTurns });
      return;
    }
    set({ liveTurns: { ...get().liveTurns, [key]: trace } });
  },
  registerFlush: (flush) => set({ flushCallback: flush }),
  flushPendingSave: () => {
    const flush = get().flushCallback;
    if (flush) flush();
  },
}));

export function useCvLiveTurn(cvId: string | null): LiveTurnTraceInput | null {
  return useCvBuilderLink((state) => (cvId === null ? undefined : state.liveTurns[turnKey(cvId)])) ?? null;
}
