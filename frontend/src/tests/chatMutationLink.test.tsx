import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { ChatWidget } from "@/features/chat/components/chat/ChatWidget";
import { useCvBuilderLink } from "@/stores/cvBuilderLinkStore";
import { useChatStore } from "@/stores/chatStore";
import type { ChatStreamCallbacks } from "@/api/chatStream";

const streamChatMessage = vi.hoisted(() => vi.fn());
const api = vi.hoisted(() => ({
  fetchChatSessions: vi.fn(),
  fetchMessages: vi.fn(),
  createChatSession: vi.fn(),
}));

vi.mock("@/api/chatStream", () => ({
  streamChatMessage: (
    sessionId: string,
    content: string,
    callbacks: ChatStreamCallbacks,
    signal?: AbortSignal,
  ) => streamChatMessage(sessionId, content, callbacks, signal),
}));

vi.mock("@/api/universities", () => ({
  fetchChatSessions: api.fetchChatSessions,
  fetchMessages: api.fetchMessages,
  createChatSession: api.createChatSession,
}));

vi.mock("@/api/ai", () => ({
  fetchAiTools: vi.fn().mockResolvedValue([]),
  transcribeAudio: vi.fn(),
  classifyDictationError: vi.fn(),
}));

const session = {
  id: "s-1",
  title: "Career chat",
  context: {},
  created_at: "2026-09-11T09:00:00Z",
};

function pendingStream(): { callbacks: ChatStreamCallbacks; finish: () => void } {
  const callbacks = {} as ChatStreamCallbacks;
  let finish: () => void = () => {};
  streamChatMessage.mockImplementation(
    (_id: string, _content: string, cbs: ChatStreamCallbacks) => {
      Object.assign(callbacks, cbs);
      return new Promise<void>((resolve) => {
        finish = () => resolve();
      });
    },
  );
  return { callbacks, finish: () => finish() };
}

async function sendSurface(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
  await user.type(screen.getByRole("textbox", { name: "Message" }), "tighten summary");
  await user.keyboard("{Enter}");
  await vi.advanceTimersByTimeAsync(40);
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  api.fetchChatSessions.mockReset().mockResolvedValue([session]);
  api.fetchMessages.mockReset().mockResolvedValue([]);
  api.createChatSession.mockReset();
  useChatStore.setState({
    sessions: [session] as never,
    activeSessionId: "s-1",
    messages: [],
    chatMode: "bubble" as never,
    bubbleOpen: false,
  });
  useCvBuilderLink.setState({ lastBuilderState: null, flushCallback: null, dataRevision: 0 });
});

afterEach(() => {
  useCvBuilderLink.setState({ lastBuilderState: null, flushCallback: null });
  useChatStore.setState({ sessions: [], activeSessionId: null, messages: [] });
  vi.useRealTimers();
});

describe("chat mutation tools bump the builder link (plan 104)", () => {
  it("a done variant_pin card bumps dataRevision once; read tools never do", async () => {
    const { callbacks, finish } = pendingStream();
    render(
      <MemoryRouter>
        <ChatWidget />
      </MemoryRouter>,
    );
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await sendSurface(user);

    await act(async () => {
      callbacks.onFlowEvent?.({
        event: "tool_call",
        payload: {
          id: "search_jobs-1",
          name: "search_jobs",
          title: "Searching jobs",
          status: "done",
          duration_ms: 40,
        },
      });
    });
    await vi.advanceTimersByTimeAsync(40);
    expect(useCvBuilderLink.getState().dataRevision).toBe(0);

    await act(async () => {
      callbacks.onFlowEvent?.({
        event: "tool_call",
        payload: {
          id: "variant_pin-1",
          name: "variant_pin",
          title: "Set default variant",
          status: "done",
          duration_ms: 30,
        },
      });
    });
    await vi.advanceTimersByTimeAsync(40);
    expect(useCvBuilderLink.getState().dataRevision).toBe(1);

    await act(async () => {
      callbacks.onFlowEvent?.({
        event: "node_started",
        payload: { id: "generate", label: "Writing the reply" },
      });
    });
    await vi.advanceTimersByTimeAsync(40);
    expect(useCvBuilderLink.getState().dataRevision).toBe(1);

    await act(async () => {
      finish();
    });
    await vi.advanceTimersByTimeAsync(0);
  });
});
