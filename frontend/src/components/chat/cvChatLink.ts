import { createChatSession } from "@/api/universities";
import { useChatStore, type ChatMode } from "@/stores/chatStore";
import type { ChatSession } from "@/types";
import { cvBuilderContext } from "@/types/cvAssistant";

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
 * Open the ONE chatbot bound to a CV: adopt the pinned
 * session for this CV or create a bound one, make it the active
 * session, and show the requested surface shape (docked side column by
 * default; "popup" is the floating bubble launcher).
 */
export async function openCvChat(
  cvId: string,
  mode: ChatMode = "docked",
): Promise<void> {
  const store = useChatStore.getState();
  const pinned = store.pinnedAsks[cvAskKey(cvId)];
  if (pinned) {
    await store.openSession(pinned);
  } else {
    const session = await createChatSession({
      title: "CV assistant",
      context: cvBuilderContext(cvId),
    });
    useChatStore.setState({
      sessions: [session, ...useChatStore.getState().sessions],
    });
    store.pinAsk(cvAskKey(cvId), session.id);
    await store.openSession(session.id);
  }
  store.setChatMode(mode);
}
