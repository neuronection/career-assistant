import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useMatch } from "react-router-dom";

import * as uniApi from "@/api/universities";
import { useChatStore } from "@/stores/chatStore";
import { createChatTransport, type CareerChatTransport } from "@/components/chat/chatTransport";
import { getDraft, writeDraft } from "@/components/chat/drafts";
import { activeCvId, cvTitle } from "@/components/chat/cvChatLink";
import { useCvBuilderLink } from "@/stores/cvBuilderLinkStore";
import { useProfileProposalsStore } from "@/stores/profileProposalsStore";
import { useTemplatePreviewsStore } from "@/stores/templatePreviewsStore";
import type { CvAssistantState } from "@/types/cvAssistant";
import {
  useChatStream,
  type ChatMessageView,
} from "@/components/ui/chat";
import type { FlowStep } from "@/components/ui";

/** Write-scope tools whose completion changes a CV's resolved content. */
const CHAT_MUTATION_TOOLS = new Set([
  "variant_pin",
  "cv_synth_generate",
  "cv_synth_update",
]);

/** The open Studio CV id, or null. */
export function useOpenStudioCv(): string | null {
  return useMatch("/cv/:id")?.params.id ?? null;
}

/**
 * Career chat wiring shared by the bubble widget and the full page
 *: sessions/messages come from the zustand store, the live
 * turn runs on the library's `useChatStream` through the SSE adapter.
 * Provided once per surface via `CareerChatProvider`. Drafts persist per
 * session.
 */
export function useCareerChat() {
  const sessions = useChatStore((state) => state.sessions);
  const activeSessionId = useChatStore((state) => state.activeSessionId);
  const messages = useChatStore((state) => state.messages);
  const loadSessions = useChatStore((state) => state.loadSessions);
  const openSession = useChatStore((state) => state.openSession);
  const newSession = useChatStore((state) => state.newSession);
  const refresh = useChatStore((state) => state.refresh);

  const [draft, setDraftState] = useState(() => getDraft(activeSessionId));
  const attachments = useChatStore((state) => state.attachments);

  useEffect(() => {
    setDraftState(getDraft(activeSessionId));
  }, [activeSessionId]);

  const changeDraft = (value: string) => {
    setDraftState(value);
    writeDraft(useChatStore.getState().activeSessionId, value);
  };

  const attachCv = useChatStore((state) => state.attachCv);
  const storeDetachCv = useChatStore((state) => state.detachCv);

  const pendingCvAttach = useChatStore((state) => state.pendingCvAttach);
  useEffect(() => {
    if (pendingCvAttach === null || activeSessionId === null) {
      return;
    }
    attachCv(pendingCvAttach);
    useChatStore.getState().setPendingCvAttach(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingCvAttach, activeSessionId]);

  // Auto-attach the open Studio CV: on /cv/:id the assistant answers
  // about the CV in view without asking. Detaching (the chip's X)
  // suppresses the re-attach for this CV until the route leaves it —
  // the paperclip picker re-attaches on demand.
  const openCvId = useOpenStudioCv();
  const detachedHere = useRef<Set<string>>(new Set());
  const prevOpenCv = useRef<string | null>(null);
  useEffect(() => {
    if (openCvId !== prevOpenCv.current) {
      detachedHere.current.clear();
      prevOpenCv.current = openCvId;
    }
    if (
      openCvId === null ||
      detachedHere.current.has(openCvId) ||
      useChatStore
        .getState()
        .attachments.some((entry) => entry.cv_id === openCvId)
    ) {
      return;
    }
    let cancelled = false;
    void cvTitle(openCvId).then((title) => {
      if (cancelled || detachedHere.current.has(openCvId)) {
        return;
      }
      // A chat without messages has no conversation to protect: the
      // open CV is THE reference, so the previous auto chip yields.
      // Once the conversation started, references accumulate as before.
      const fresh = useChatStore.getState().messages.length === 0;
      if (fresh) {
        useChatStore.getState().autoAttachCv({ id: openCvId, title });
      } else {
        attachCv({ id: openCvId, title });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [openCvId, attachments, attachCv]);

  const detachCv = (cvId: string) => {
    detachedHere.current.add(cvId);
    storeDetachCv(cvId);
  };

  const transportRef = useRef<CareerChatTransport | null>(null);
  const linkNotified = useRef<Set<string>>(new Set());
  if (transportRef.current === null) {
    transportRef.current = createChatTransport({
      getSessionId: () => useChatStore.getState().activeSessionId,
      // Copilot turns: the terminal `builder_state` payload is
      // forwarded to the link store; the builder page — when mounted —
      // re-syncs from it. Other pages simply ignore it.
      onBuilderState: (state) =>
        useCvBuilderLink
          .getState()
          .applyBuilderState(state as unknown as CvAssistantState),
      // HITL proposal cards (plan 77): stream into the shared store so
      // every surface renders them live; the persisted pair that lands
      // with `refresh` takes over rendering.
      onProposal: (card) => useProfileProposalsStore.getState().receiveLive(card),
      // Template previews (plan 83): stream into the live store; the
      // persisted metadata takes over once the turn completes.
      onPreview: (preview) =>
        useTemplatePreviewsStore.getState().receiveLive(preview),
      onFlowEvent: (event) => {
        if (event.event === "flow_started") {
          useTemplatePreviewsStore.getState().reset();
        }
      },
    });
  }
  const stream = useChatStream({ transport: transportRef.current });
  const reset = stream.reset;
  const sending = stream.status === "pending" || stream.status === "streaming";

  useEffect(() => {
    // Reconcile card statuses from the list endpoint (metadata is a
    // snapshot; resolves elsewhere — other surface, session deleted —
    // must flip cards here too).
    void useProfileProposalsStore.getState().hydrate();
  }, []);

  useEffect(() => {
    // Done turns refetch the persisted pair; interrupted turns now persist
    // their partial server-side so they refresh too. Error turns refresh
    // WITHOUT resetting: the user message is already persisted server-side
    // (the turn saves it before the LLM runs) — it must appear in the
    // transcript even when the reply failed — while the live error tile
    // (Retry) stays until the user retries or sends again.
    if (
      stream.status !== "done" &&
      stream.status !== "interrupted" &&
      stream.status !== "error"
    ) {
      return;
    }
    const sessionId = useChatStore.getState().activeSessionId;
    if (sessionId === null) {
      return;
    }
    let cancelled = false;
    void (async () => {
      await refresh(sessionId);
      if (!cancelled && stream.status !== "error") {
        reset();
        useProfileProposalsStore.getState().clearLive();
        void useProfileProposalsStore.getState().hydrate();
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [stream.status, refresh, reset]);

  const lastResolved = useProfileProposalsStore((state) => state.lastResolved);
  useEffect(() => {
    // Auto-continue (plan 77.1 follow-on): when the resolution burst for
    // THIS session ends — its last card hit a terminal state and none are
    // left pending — the assistant answers once from a visible synthetic
    // user message (the transcript stays honest). The store's
    // `claimFollowup` guard makes multiple mounted surfaces
    // double-send-proof, the `(resolved card: …)` prefix on the previous
    // user message prevents chaining, and a resolve that happened while
    // this surface was mid-turn waits for the stream to idle.
    if (
      lastResolved === null ||
      stream.status !== "idle" ||
      lastResolved.sessionId === null ||
      lastResolved.sessionId !== activeSessionId
    ) {
      return;
    }
    const proposalsStore = useProfileProposalsStore.getState();
    if ((proposalsStore.pendingBySession[lastResolved.sessionId] ?? 0) > 0) {
      return;
    }
    const messages = useChatStore.getState().messages;
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (!lastUser || lastUser.content.startsWith("(resolved card:")) {
      return;
    }
    if (
      lastResolved.status !== "approved" &&
      lastResolved.status !== "rejected"
    ) {
      return;
    }
    const key = `${lastResolved.id}:${lastResolved.status}`;
    if (!proposalsStore.claimFollowup(key)) {
      return;
    }
    void stream.send(
      `(resolved card: ${lastResolved.title} — ${lastResolved.status})`,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastResolved, stream.status]);

  useEffect(() => {
    // Plan 67: the builder page mirrors the live turn's flow events
    // (node/tool snapshots, never text deltas) — keyed by the CV the
    // session is bound to. reset() returns the stream to idle, which
    // clears the mirror once the persisted trace landed (refresh above).
    const store = useChatStore.getState();
    const cvId = activeCvId(store.sessions, store.activeSessionId);
    if (cvId === null) {
      return;
    }
    if (stream.status === "idle") {
      useCvBuilderLink.getState().applyTurnTrace(cvId, null);
      return;
    }
    useCvBuilderLink.getState().applyTurnTrace(cvId, {
      status: stream.status,
      nodes: stream.nodes,
      toolCalls: stream.toolCalls,
      startedAt: stream.startedAt,
      error: stream.error ?? null,
    });
  }, [stream.status, stream.nodes, stream.toolCalls, stream.startedAt, stream.error]);

  useEffect(() => {
    // Plan 104: write-scope tools mutate CV-visible data the moment they
    // finish (variant_pin, copilot cv_synth_*). The mounted builder
    // refetches its preview — per tool card, never re-fired on re-renders.
    if (stream.toolCalls.length === 0) {
      // New/reset turn: drop the per-turn guard state.
      if (linkNotified.current.size > 0) linkNotified.current.clear();
      return;
    }
    const done = stream.toolCalls.filter(
      (call) => CHAT_MUTATION_TOOLS.has(call.name) && call.status === "done",
    );
    const fresh = done.filter((call) => !linkNotified.current.has(call.id));
    if (fresh.length === 0) {
      return;
    }
    for (const call of fresh) linkNotified.current.add(call.id);
    useCvBuilderLink.getState().notifyDataChanged();
  }, [stream.toolCalls]);

  const submit = async () => {
    // The state draft can lag the persisted one by a render (batched
    // programmatic input events) — prefer whichever holds text so a
    // submit pressed right after typing is never silently dropped.
    const content =
      draft.trim() ||
      getDraft(useChatStore.getState().activeSessionId).trim();
    if (content === "" || sending) {
      return;
    }
    if (useChatStore.getState().activeSessionId === null) {
      await newSession();
    }
    const store = useChatStore.getState();
    if (activeCvId(store.sessions, store.activeSessionId) !== null) {
      // Copilot turn on a CV-bound session: flush the editor's pending
      // debounced autosave first so ops and edits never race.
      useCvBuilderLink.getState().flushPendingSave();
    }
    writeDraft(store.activeSessionId, "");
    setDraftState("");
    const attachments = useChatStore.getState().attachments;
    transportRef.current?.setPendingAttachments(
      attachments.map(({ kind, cv_id }) => ({ kind, cv_id })),
    );
    useChatStore.getState().clearAttachments();
    // Optimistic user message: the transcript shows it immediately; the
    // done-turn refresh replaces it with the persisted pair.
    useChatStore.setState({
      messages: [
        ...store.messages,
        {
          id: `local-${Date.now()}`,
          role: "user",
          content,
          metadata_json: null,
          created_at: new Date().toISOString(),
        },
      ],
    });
    await stream.send(content);
  };

  const submitEdit = async (messageId: string, content: string) => {
    if (content.trim() === "" || sending) {
      return;
    }
    transportRef.current?.beginEdit(messageId);
    await stream.send(content);
  };

  const regenerate = async (messageId: string, content: string) => {
    if (sending) {
      return;
    }
    transportRef.current?.beginRegenerate(messageId);
    await stream.send(content);
  };

  const retry = async () => {
    if (sending) {
      return;
    }
    const current = useChatStore.getState().messages;
    const lastUser = [...current].reverse().find((message) => message.role === "user");
    if (!lastUser) {
      return;
    }
    await regenerate(lastUser.id, lastUser.content);
  };

  const selectVariant = async (messageId: string) => {
    const sessionId = useChatStore.getState().activeSessionId;
    if (sessionId === null) {
      return;
    }
    const messages = await uniApi.selectChatMessage(messageId);
    useChatStore.setState({ messages });
  };

  const flowSteps = useRef<FlowStep[] | null>(null);
  flowSteps.current =
    stream.nodes.length > 0
      ? stream.nodes.map((node) => ({ id: node.id, label: node.label ?? node.id, status: node.status }))
      : flowSteps.current;
  const currentFlowSteps = flowSteps.current ?? [];

  const viewMessages = messages.map<ChatMessageView>((message) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    status: "done",
    parentId: message.parent_id ?? null,
    variants:
      (message.variant_count ?? 1) > 1
        ? {
            index: message.variant_index ?? 1,
            count: message.variant_count ?? 1,
            siblingIds: message.sibling_ids ?? [message.id],
          }
        : undefined,
  }));

  return {
    sessions,
    activeSessionId,
    messages,
    viewMessages,
    stream,
    sending,
    flowSteps: currentFlowSteps,
    draft,
    setDraft: changeDraft,
    attachments,
    attachCv,
    detachCv,
    submit,
    submitEdit,
    regenerate,
    retry,
    selectVariant,
    loadSessions,
    openSession,
    newSession,
  };
}

export type CareerChat = ReturnType<typeof useCareerChat>;

const CareerChatContext = createContext<CareerChat | null>(null);

export function CareerChatProvider({ children }: { children: React.ReactNode }) {
  const chat = useCareerChat();
  return <CareerChatContext.Provider value={chat}>{children}</CareerChatContext.Provider>;
}

export function useCareerChatContext(): CareerChat {
  const chat = useContext(CareerChatContext);
  if (chat === null) {
    throw new Error("useCareerChatContext requires a CareerChatProvider ancestor");
  }
  return chat;
}
