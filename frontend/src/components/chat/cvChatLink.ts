import { createChatSession } from "@/api/universities";
import { writeDraft } from "@/components/chat/drafts";
import { useChatStore, type ChatMode } from "@/stores/chatStore";
import type { ChatSession } from "@/types";

export function cvAskKey(cvId: string): string {
  return `cv:${cvId}`;
}

export function isCvBoundSession(
  session: ChatSession | undefined,
): string | null {
  const context = session?.context;
  if (context?.surface === "cv_builder" && context.cv_id) {
    return String(context.cv_id);
  }
  return null;
}

export function activeCvId(
  sessions: ChatSession[],
  activeSessionId: string | null,
): string | null {
  const active = sessions.find((session) => session.id === activeSessionId);
  return isCvBoundSession(active);
}

/**
 * Open the chat with a CV attached as reference (plan 78): adopts the
 * active normal session (or the most recent one, or creates a fresh one)
 * — NEVER a builder-bound session — requests the CV attachment, and
 * optionally prefills the composer. The bound-session creation of plan
 * 53 is gone; existing bound sessions keep working (legacy read path).
 */
export async function openCvChat(
  cvId: string,
  mode: ChatMode = "docked",
  prefill?: string,
): Promise<void> {
  const store = useChatStore.getState();
  const usable = (session: ChatSession | undefined) =>
    session !== undefined &&
    isCvBoundSession(session) === null &&
    (session.context as { surface?: string } | null)?.surface !== "interview";
  const active = store.sessions.find((session) => session.id === store.activeSessionId);
  const normal =
    usable(active)
      ? active
      : store.sessions.find((session) => usable(session));
  let sessionId: string;
  if (normal) {
    sessionId = normal.id;
  } else {
    const session = await createChatSession({ title: "CV chat" });
    useChatStore.setState({
      sessions: [session, ...useChatStore.getState().sessions],
    });
    sessionId = session.id;
  }
  if (prefill) {
    writeDraft(sessionId, prefill);
  }
  // Settle the session + surface FIRST, then request the one-shot
  // attach: the consumer runs once the target session is active, so
  // the reference can't be wiped by the session transition (chips are
  // store-owned and cleared on session switches).
  await useChatStore.getState().openSession(sessionId);
  useChatStore.getState().setChatMode(mode);
  const title = await cvTitle(cvId);
  useChatStore.getState().setPendingCvAttach({ id: cvId, title });
}

/** Display title for a CV id, falling back to a generic label. */
export async function cvTitle(cvId: string): Promise<string> {
  try {
    const { fetchCvs } = await import("@/api/cv");
    const rows = await fetchCvs();
    return rows.find((row) => row.id === cvId)?.title ?? "CV";
  } catch {
    return "CV";
  }
}
