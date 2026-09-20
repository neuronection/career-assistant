import { create } from "zustand";
import * as uniApi from "@/api/universities";
import type { ChatCvAttachment, ChatMessage, ChatSession } from "@/types";

export type ChatMode = "bubble" | "docked";

const CHAT_MODE_KEY = "ca:chat:mode";

function loadPersistedChatMode(): ChatMode {
  if (typeof localStorage === "undefined") return "docked";
  return localStorage.getItem(CHAT_MODE_KEY) === "bubble" ? "bubble" : "docked";
}

function persistChatMode(mode: ChatMode) {
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(CHAT_MODE_KEY, mode);
}

interface ChatState {
  sessions: ChatSession[];
  activeSessionId: string | null;
  messages: ChatMessage[];
  /** Chat surface mode: floating bubble launcher or docked resizable
   * side column ( review — one chatbot, three shapes: bubble,
   *  docked, page). The page stays route-based (/chat). */
  chatMode: ChatMode;
  /** Whether the bubble panel is expanded — transient, never persisted.
   *  Store-owned so the /chat page can close the floating window and
   *  take over its active conversation (one open surface at a time). */
  bubbleOpen: boolean;
  /** One pinned chat session per entity surface, keyed `cv:{id}` —
   *  study's `viewerAsks` pattern: the CV-builder copilot reuses its
   *  session instead of spawning a new one per visit. */
  pinnedAsks: Record<string, string>;
  loadSessions: () => Promise<void>;
  openSession: (id: string) => Promise<void>;
  newSession: () => Promise<ChatSession>;
  resetToDraft: () => void;
  renameSession: (id: string, title: string) => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
  pinAsk: (key: string, sessionId: string) => void;
  /** One-shot CV attachment request (plan 78): set by openCvChat,
   * consumed by the chat hook once a session is active. */
  pendingCvAttach: { id: string; title: string } | null;
  setPendingCvAttach: (cv: { id: string; title: string } | null) => void;
  /** Composer CV references for the active session (plan 78). Store-owned
   * so the chips survive surface switches (bubble ↔ dock ↔ page) and the
   * session transition openCvChat performs after requesting the attach —
   * per-surface local state lost them between `setPendingCvAttach` and
   * `openSession` settling (the send then carried no attachments). */
  attachments: ChatCvAttachment[];
  attachCv: (cv: { id: string; title: string }) => void;
  detachCv: (cvId: string) => void;
  clearAttachments: () => void;
  setChatMode: (mode: ChatMode) => void;
  setBubbleOpen: (open: boolean) => void;
  /** Refetch the persisted turn after a streamed reply lands. */
  refresh: (sessionId: string) => Promise<void>;
  reset: () => void;
}

/** Sessions + persisted messages; the live turn lives in `useChatStream`
 *  fed by `createChatTransport` (streaming state stays out of the store). */
export const useChatStore = create<ChatState>((set, get) => ({
  sessions: [],
  activeSessionId: null,
  messages: [],
  chatMode: loadPersistedChatMode(),
  bubbleOpen: false,
  pinnedAsks: {},
  pendingCvAttach: null,
  attachments: [],

  loadSessions: async () => {
    const sessions = await uniApi.fetchChatSessions();
    set({ sessions });
  },

  openSession: async (id) => {
    const messages = await uniApi.fetchMessages(id);
    // Composer references belong to the conversation: switching sessions
    // drops them (the pending one-shot survives — it is consumed after
    // this settles by the openCvChat flow). Bootstrap is not a switch:
    // with no session active yet (or the target already claimed), the
    // attachments were added FOR this conversation — keep them.
    const switching =
      get().activeSessionId !== null && get().activeSessionId !== id;
    set({
      activeSessionId: id,
      messages,
      attachments: switching ? [] : get().attachments,
    });
  },

  newSession: async () => {
    const session = await uniApi.createChatSession({});
    set({ sessions: [session, ...get().sessions], activeSessionId: session.id, messages: [] });
    return session;
  },

  resetToDraft: () => {
    set({
      activeSessionId: null,
      messages: [],
      pendingCvAttach: null,
      attachments: [],
    });
  },

  renameSession: async (id, title) => {
    await uniApi.renameChatSession(id, title);
    set({
      sessions: get().sessions.map((session) =>
        session.id === id ? { ...session, title } : session,
      ),
    });
  },

  deleteSession: async (id) => {
    await uniApi.deleteChatSession(id);
    const sessions = get().sessions.filter((session) => session.id !== id);
    const activeSessionId =
      get().activeSessionId === id ? null : get().activeSessionId;
    const pinnedAsks = Object.fromEntries(
      Object.entries(get().pinnedAsks).filter(([, sessionId]) => sessionId !== id),
    );
    set({
      sessions,
      activeSessionId,
      pinnedAsks,
      messages: activeSessionId === null ? [] : get().messages,
      attachments: activeSessionId === null ? [] : get().attachments,
    });
  },

  pinAsk: (key, sessionId) => {
    set({ pinnedAsks: { ...get().pinnedAsks, [key]: sessionId } });
  },

  setPendingCvAttach: (cv) => {
    set({ pendingCvAttach: cv });
  },

  attachCv: (cv) => {
    const current = get().attachments;
    if (current.some((entry) => entry.cv_id === cv.id) || current.length >= 2) {
      return;
    }
    set({
      attachments: [
        ...current,
        { kind: "cv", cv_id: cv.id, title: cv.title },
      ],
    });
  },

  detachCv: (cvId) => {
    set({
      attachments: get().attachments.filter((entry) => entry.cv_id !== cvId),
    });
  },

  clearAttachments: () => {
    set({ attachments: [] });
  },

  setChatMode: (mode) => {
    persistChatMode(mode);
    set({ chatMode: mode });
  },

  setBubbleOpen: (open) => {
    set({ bubbleOpen: open });
  },

  refresh: async (sessionId) => {
    const [messages, sessions] = await Promise.all([
      uniApi.fetchMessages(sessionId),
      uniApi.fetchChatSessions(),
    ]);
    set({ messages, sessions });
  },

  reset: () => {
    persistChatMode("docked");
    set({
      sessions: [],
      activeSessionId: null,
      messages: [],
      pinnedAsks: {},
      chatMode: "docked",
      bubbleOpen: false,
      pendingCvAttach: null,
      attachments: [],
    });
  },
}));
