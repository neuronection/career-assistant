import { create } from "zustand";

import type { ChatTemplatePreview } from "@/types";

interface TemplatePreviewsState {
  /** Previews streamed live during the current copilot turn. */
  live: ChatTemplatePreview[];
  receiveLive: (preview: ChatTemplatePreview) => void;
  reset: () => void;
}

/** Plan 83: live template previews streamed before the copilot plans
 * (`preview` SSE events). Persisted metadata on the assistant message
 * takes over rendering once the turn completes. */
export const useTemplatePreviewsStore = create<TemplatePreviewsState>()(
  (set) => ({
    live: [],
    receiveLive: (preview) =>
      set((state) =>
        state.live.some((entry) => entry.template_id === preview.template_id)
          ? state
          : { live: [...state.live, preview] },
      ),
    reset: () => set({ live: [] }),
  }),
);
