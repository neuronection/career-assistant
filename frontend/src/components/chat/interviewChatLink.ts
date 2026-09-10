import { useChatStore, type ChatMode } from "@/stores/chatStore";
import type { ChatSession } from "@/types";

export function isInterviewBoundSession(
  session: ChatSession | undefined,
): string | null {
  const context = session?.context;
  if (context?.surface === "interview" && context.interview_id) {
    return String(context.interview_id);
  }
  return null;
}

/**
 * Open the ONE chatbot on an interview practice session: the
 * chat session was created server-side by the start endpoint — make it
 * the active session and show the requested surface shape.
 */
export async function openInterviewChat(
  chatSessionId: string,
  mode: ChatMode = "docked",
): Promise<void> {
  const store = useChatStore.getState();
  if (!store.sessions.some((session) => session.id === chatSessionId)) {
    await store.loadSessions();
  }
  await store.openSession(chatSessionId);
  store.setChatMode(mode);
}
