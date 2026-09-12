import { createContext, useContext, useEffect, useRef, useState } from "react";

import * as uniApi from "@/api/universities";
import { useChatStore } from "@/stores/chatStore";
import { createChatTransport, type CareerChatTransport } from "@/components/chat/chatTransport";
import { getDraft, writeDraft } from "@/components/chat/drafts";
import { activeCvId } from "@/components/chat/cvChatLink";
import { useCvBuilderLink } from "@/stores/cvBuilderLinkStore";
import type { CvAssistantState } from "@/types/cvAssistant";
import {
  useChatStream,
  type ChatMessageView,
} from "@/components/ui/chat";
import type { FlowStep } from "@/components/ui";

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

  useEffect(() => {
    setDraftState(getDraft(activeSessionId));
  }, [activeSessionId]);

  const changeDraft = (value: string) => {
    setDraftState(value);
    writeDraft(useChatStore.getState().activeSessionId, value);
  };

  const transportRef = useRef<CareerChatTransport | null>(null);
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
    });
  }
  const stream = useChatStream({ transport: transportRef.current });
  const reset = stream.reset;
  const sending = stream.status === "pending" || stream.status === "streaming";

  useEffect(() => {
    // Done turns refetch the persisted pair; interrupted turns now persist
    // their partial server-side so they refresh
    // too. Errors stay live until the user retries or sends again.
    if (stream.status !== "done" && stream.status !== "interrupted") {
      return;
    }
    const sessionId = useChatStore.getState().activeSessionId;
    if (sessionId === null) {
      return;
    }
    let cancelled = false;
    void (async () => {
      await refresh(sessionId);
      if (!cancelled) {
        reset();
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [stream.status, refresh, reset]);

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

  const submit = async () => {
    const content = draft.trim();
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
