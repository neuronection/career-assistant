import { create } from "zustand";

import {
  approveProfileProposal,
  fetchProfileProposals,
  getProposalPreview,
  rejectProfileProposal,
  revertProfileProposal,
  type ProfileProposalPreviewData,
} from "@/api/profileProposals";
import { useCvBuilderLink } from "@/stores/cvBuilderLinkStore";
import type { ProfileProposalCardData } from "@/types";

export interface ResolvedProposalEvent {
  id: string;
  sessionId: string | null;
  title: string;
  action: "approve" | "reject";
  status: ProfileProposalCardData["status"];
}

export type ProposalPreviewEntry =
  | { state: "ready"; data: ProfileProposalPreviewData }
  | { state: "missing" };

/** Kinds with snapshot-backed previews (plan 99 AD7, 101 AD2: cv_synth
 * previews before-only); the rest 404. */
export const PREVIEW_KINDS = new Set([
  "experience_item",
  "education_item",
  "certification",
  "profile_achievement",
  "cv_synth",
]);

/**
 * HITL proposal cards (plan 77): live-turn cards stream in through the
 * transport (`receiveLive`, the builder_state pattern); persisted cards
 * render from message metadata. Resolve results live here as status
 * overrides so every surface (bubble/docked/page) flips in sync without
 * refetching the transcript — the list endpoint remains the source of
 * truth (`hydrate` reconciles stale metadata snapshots).
 *
 * Plan-81.1 auto-continue: `lastResolved` + `pendingBySession` let a chat
 * surface detect that the resolution burst for ITS session ended and
 * answer once (the guard keys live here so two mounted surfaces can never
 * double-send — `lastFollowupKey` is consumed atomically).
 *
 * Plan-99.6: the preview cache is transient (prop id → before/after data
 * or `missing`), only filled lazily when a preview modal opens; a 404
 * marks the card so its preview button hides instead of erroring again.
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
  /** Pending cards per chat session (burst detection, auto-continue). */
  pendingBySession: Record<string, number>;
  /** Most recent successful terminal resolve — the burst watch signal. */
  lastResolved: ResolvedProposalEvent | null;
  /** Followup-sent guard, shared store → one send max per burst. */
  lastFollowupKey: string | null;
  /** Lazy preview payloads per proposal id (fresh while the app runs). */
  previews: Record<string, ProposalPreviewEntry>;
  receiveLive: (card: ProfileProposalCardData) => void;
  clearLive: () => void;
  setBusy: (id: string, busy: boolean) => void;
  resolve: (id: string, action: "approve" | "reject") => Promise<void>;
  revert: (id: string) => Promise<void>;
  loadPreview: (
    id: string,
  ) => Promise<ProposalPreviewEntry | null>;
  hydrate: () => Promise<void>;
  claimFollowup: (key: string) => boolean;
}

export const useProfileProposalsStore = create<ProfileProposalsState>(
  (set, get) => ({
    live: [],
    overrides: {},
    pendingCount: 0,
    pendingBySession: {},
    lastResolved: null,
    lastFollowupKey: null,
    previews: {},
    receiveLive: (card) => {
      const sessionKey = card.chat_session_id ?? "";
      set((state) => ({
        live: [...state.live.filter((c) => c.id !== card.id), card],
        pendingCount: state.pendingCount + 1,
        pendingBySession: sessionKey
          ? {
              ...state.pendingBySession,
              [sessionKey]: (state.pendingBySession[sessionKey] ?? 0) + 1,
            }
          : state.pendingBySession,
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
        const resolved = response.proposal;
        const status = resolved.status;
        set((state) => {
          const live = state.live.map((card) =>
            card.id === id ? { ...card, status } : card,
          );
          const delta = current.status === "pending" ? -1 : 0;
          const sessionKey = resolved.chat_session_id ?? null;
          const pendingBySession = sessionKey
            ? {
                ...state.pendingBySession,
                [sessionKey]: Math.max(
                  0,
                  (state.pendingBySession[sessionKey] ?? 0) - 1,
                ),
              }
            : state.pendingBySession;
          return {
            live,
            pendingCount: Math.max(0, state.pendingCount + delta),
            pendingBySession,
            overrides: {
              ...state.overrides,
              [id]: { status, busy: false },
            },
            lastResolved: {
              id,
              sessionId: sessionKey,
              title: resolved.title,
              action,
              status,
            },
          };
        });
        // Rebase from the server truth: live-card optimistic deltas can
        // drift (conflict flips a card back, multi-device resolves).
        await get().hydrate();
        // Plan 104: an approval mutated profile/variant data server-side
        // — the mounted CV builder refetches its resolved preview.
        if (action === "approve" && status === "approved") {
          useCvBuilderLink.getState().notifyDataChanged();
        }
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
        const pendingBySession: Record<string, number> = {};
        for (const card of proposals) {
          if (card.status !== "pending") {
            overrides[card.id] = { status: card.status };
          } else if (card.chat_session_id) {
            pendingBySession[card.chat_session_id] =
              (pendingBySession[card.chat_session_id] ?? 0) + 1;
          }
        }
        set((state) => ({
          overrides: { ...overrides, ...state.overrides },
          pendingCount: pending_count,
          pendingBySession,
        }));
      } catch {
        // Hydration is best-effort — cards still render from metadata.
      }
    },
    claimFollowup: (key) => {
      if (get().lastFollowupKey === key) {
        return false;
      }
      set({ lastFollowupKey: key });
      return true;
    },
    revert: async (id) => {
      const current = get().overrides[id];
      set((state) => ({
        overrides: {
          ...state.overrides,
          [id]: {
            status: current?.status ?? "approved",
            busy: true,
            error: undefined,
          },
        },
      }));
      try {
        const card = await revertProfileProposal(id);
        set((state) => ({
          live: state.live.map((c) =>
            c.id === id ? { ...c, status: card.status } : c,
          ),
          overrides: {
            ...state.overrides,
            [id]: { status: card.status, busy: false },
          },
          lastResolved: {
            id,
            sessionId: card.chat_session_id ?? null,
            title: card.title,
            action: "reject",
            status: card.status,
          },
        }));
        // Plan 104: the revert restored the pre-edit entity — refresh.
        useCvBuilderLink.getState().notifyDataChanged();
      } catch (error) {
        const detail =
          (error as { response?: { data?: { detail?: string } } })?.response
            ?.data?.detail ?? "Revert failed";
        set((state) => ({
          overrides: {
            ...state.overrides,
            [id]: { status: current?.status ?? "approved", busy: false, error: detail },
          },
        }));
      }
    },
    loadPreview: async (id) => {
      const cached = get().previews[id];
      if (cached) {
        return cached;
      }
      try {
        const data = await getProposalPreview(id);
        const entry: ProposalPreviewEntry = { state: "ready", data };
        set((state) => ({
          previews: { ...state.previews, [id]: entry },
        }));
        return entry;
      } catch {
        set((state) => ({
          previews: { ...state.previews, [id]: { state: "missing" } },
        }));
        return { state: "missing" };
      }
    },
  }),
);
