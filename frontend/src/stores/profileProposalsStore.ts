import { create } from "zustand";

import {
  approveProfileProposal,
  fetchProfileProposals,
  rejectProfileProposal,
} from "@/api/profileProposals";
import type { ProfileProposalCardData } from "@/types";

/**
 * HITL proposal cards (plan 77): live-turn cards stream in through the
 * transport (`receiveLive`, the builder_state pattern); persisted cards
 * render from message metadata. Resolve results live here as status
 * overrides so every surface (bubble/docked/page) flips in sync without
 * refetching the transcript — the list endpoint remains the source of
 * truth (`hydrate` reconciles stale metadata snapshots).
 */
interface ProfileProposalsState {
  /** Cards emitted by the current live turn (cleared once persisted). */
  live: ProfileProposalCardData[];
  /** Resolve results keyed by proposal id (status + error + applied kind). */
  overrides: Record<
    string,
    { status: ProfileProposalCardData["status"]; error?: string; busy?: boolean }
  >;
  pendingCount: number;
  receiveLive: (card: ProfileProposalCardData) => void;
  clearLive: () => void;
  setBusy: (id: string, busy: boolean) => void;
  resolve: (id: string, action: "approve" | "reject") => Promise<void>;
  hydrate: () => Promise<void>;
}

export const useProfileProposalsStore = create<ProfileProposalsState>(
  (set, get) => ({
    live: [],
    overrides: {},
    pendingCount: 0,
    receiveLive: (card) => {
      set((state) => ({
        live: [...state.live.filter((c) => c.id !== card.id), card],
        pendingCount: state.pendingCount + 1,
      }));
    },
    clearLive: () => {
      // Persisted cards take over rendering; pendingCount is rebased by
      // hydrate() — the proposals still exist server-side.
      set({ live: [] });
    },
    setBusy: (id, busy) => {
      const current = get().overrides[id] ?? {
        status: "pending" as const,
      };
      set((state) => ({
        overrides: { ...state.overrides, [id]: { ...current, busy } },
      }));
    },
    resolve: async (id, action) => {
      const current = get().overrides[id] ?? { status: "pending" as const };
      set((state) => ({
        overrides: {
          ...state.overrides,
          [id]: { ...current, busy: true, error: undefined },
        },
      }));
      try {
        const response =
          action === "approve"
            ? await approveProfileProposal(id)
            : await rejectProfileProposal(id);
        const status = response.proposal.status;
        set((state) => {
          const live = state.live.map((card) =>
            card.id === id ? { ...card, status } : card,
          );
          const delta =
            action === "approve" && status === "approved"
              ? state.live.some((card) => card.id === id && card.status === "pending")
                ? -1
                : 0
              : state.live.some((card) => card.id === id && card.status === "pending")
                ? -1
                : 0;
          return {
            live,
            pendingCount: Math.max(0, state.pendingCount + delta),
            overrides: {
              ...state.overrides,
              [id]: { status, busy: false },
            },
          };
        });
      } catch (error) {
        const detail =
          (error as { response?: { data?: { detail?: string } } })?.response?.data
            ?.detail ?? "Resolve failed";
        // 409 conflict: the backend flips the proposal to conflict with a
        // fresh diff — reflect it without losing the card.
        set((state) => ({
          overrides: {
            ...state.overrides,
            [id]: {
              status: detail.toLowerCase().includes("changed") ? "conflict" : "pending",
              error: detail,
              busy: false,
            },
          },
        }));
      }
    },
    hydrate: async () => {
      try {
        const { proposals, pending_count } = await fetchProfileProposals();
        const overrides: ProfileProposalsState["overrides"] = {};
        for (const card of proposals) {
          if (card.status !== "pending") {
            overrides[card.id] = { status: card.status };
          }
        }
        set((state) => ({
          overrides: { ...overrides, ...state.overrides },
          pendingCount: pending_count,
        }));
      } catch {
        // Hydration is best-effort — cards still render from metadata.
      }
    },
  }),
);
