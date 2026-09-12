import { create } from "zustand";
import * as uniApi from "@/api/universities";
import type { ChatMessage, ChatSession } from "@/types";

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
  /** One pinned chat session per entity surface, keyed `cv:{id}` —
   *  study's `viewerAsks` pattern: the CV-builder copilot reuses its
   *  session instead of spawning a new one per visit. */
  pinnedAsks: Record<string, string>;
  loadSessions: () => Promise<void>;
  openSession: (id: string) => Promise<void>;
  newSession: () => Promise<ChatSession>;
  renameSession: (id: string, title: string) => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
  pinAsk: (key: string, sessionId: string) => void;
  setChatMode: (mode: ChatMode) => void;
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
  pinnedAsks: {},

  loadSessions: async () => {
    const sessions = await uniApi.fetchChatSessions();
    set({ sessions });
  },

  openSession: async (id) => {
    const messages = await uniApi.fetchMessages(id);
    set({ activeSessionId: id, messages });
  },

  newSession: async () => {
    const session = await uniApi.createChatSession({});
    set({ sessions: [session, ...get().sessions], activeSessionId: session.id, messages: [] });
    return session;
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
    });
  },

  pinAsk: (key, sessionId) => {
    set({ pinnedAsks: { ...get().pinnedAsks, [key]: sessionId } });
  },

  setChatMode: (mode) => {
    persistChatMode(mode);
    set({ chatMode: mode });
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
    });
  },
}));
