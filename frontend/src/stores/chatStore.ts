import { create } from "zustand";
import * as uniApi from "@/api/universities";
import { streamChatMessage } from "@/api/chatStream";
import type { ChatMessage, ChatSession } from "@/types";

interface ChatState {
  sessions: ChatSession[];
  activeSessionId: string | null;
  messages: ChatMessage[];
  sending: boolean;
  /** Progressive assistant text while a streamed reply is in flight. */
  streamingText: string | null;
  streamingStage: string | null;
  loadSessions: () => Promise<void>;
  openSession: (id: string) => Promise<void>;
  newSession: () => Promise<void>;
  send: (content: string) => Promise<void>;
}

export const useChatStore = create<ChatState>((set, get) => ({
  sessions: [],
  activeSessionId: null,
  messages: [],
  sending: false,
  streamingText: null,
  streamingStage: null,

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
  },

  send: async (content) => {
    const sessionId = get().activeSessionId;
    if (!sessionId) return;
    set({ sending: true, streamingText: null, streamingStage: "thinking…" });
    try {
      await streamChatMessage(sessionId, content, {
        onStatus: (stage) => set({ streamingStage: stage }),
        onDelta: (accumulated) => set({ streamingText: accumulated, streamingStage: null }),
      });
      const appended = await uniApi.fetchMessages(sessionId);
      set({ messages: appended });
      const sessions = get().sessions;
      const current = sessions.find((s) => s.id === sessionId);
      if (current && current.title === "New chat") {
        current.title = content.slice(0, 40);
        set({ sessions: [...sessions] });
      }
    } finally {
      set({ sending: false, streamingText: null, streamingStage: null });
    }
  },
}));
