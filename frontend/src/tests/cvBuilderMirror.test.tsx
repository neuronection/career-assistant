import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { ChatWidget } from "@/components/chat/ChatWidget";
import { CopilotActivityCard } from "@/components/cv/CopilotActivityCard";
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

function renderSurface() {
  return render(
    <MemoryRouter initialEntries={["/cv/cv-1"]}>
      <ChatWidget />
      <CopilotActivityCard cvId="cv-1" />
    </MemoryRouter>,
  );
}

const persistedTrace = {
  surface: "cv_builder",
  model: "mock-gpt",
  elapsed_ms: 1930,
  tokens_out: 320,
  nodes: [
    { id: "ground", label: "Reading the builder state", status: "done", start_ms: 0, duration_ms: 420 },
    { id: "generate", label: "Planning changes", status: "done", start_ms: 420, duration_ms: 1400 },
  ],
  tools: [
    {
      name: "get_builder_state",
      title: "Reading the draft",
      status: "done",
      args_summary: "cv_id=cv-1",
      result_summary: "3 blocks",
      start_ms: 30,
      duration_ms: 210,
    },
  ],
  operations: [{ op: "set_text", ok: true, detail: "Summary updated" }],
  version: 3,
};

const cvSession = {
  id: "s-cv",
  title: "CV assistant",
  context: { surface: "cv_builder", cv_id: "cv-1" },
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

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  api.fetchChatSessions.mockReset().mockResolvedValue([cvSession]);
  api.fetchMessages.mockReset().mockResolvedValue([]);
  api.createChatSession.mockReset();
  useChatStore.setState({
    sessions: [cvSession] as never,
    activeSessionId: "s-cv",
    messages: [],
    chatMode: "bubble" as never,
  });
  useCvBuilderLink.setState({ lastBuilderState: null, liveTurns: {}, flushCallback: null });
});

afterEach(() => {
  useCvBuilderLink.setState({ lastBuilderState: null, liveTurns: {}, flushCallback: null });
  useChatStore.setState({ sessions: [], activeSessionId: null, messages: [] });
  vi.useRealTimers();
});


describe("copilot turn mirror (plan 67.2)", () => {
  it("store keys the live trace per CV and clears only its own entry", () => {
    const a = { status: "streaming" as const, nodes: [{ id: "n1", status: "running" as const }], toolCalls: [] };
    const b = { status: "streaming" as const, nodes: [{ id: "n2", status: "running" as const }], toolCalls: [] };
    act(() => {
      useCvBuilderLink.getState().applyTurnTrace("cv-a", a);
      useCvBuilderLink.getState().applyTurnTrace("cv-b", b);
    });
    expect(useCvBuilderLink.getState().liveTurns["cv:cv-a"]).toEqual(a);
    expect(useCvBuilderLink.getState().liveTurns["cv:cv-b"]).toEqual(b);
    act(() => {
      useCvBuilderLink.getState().applyTurnTrace("cv-a", null);
    });
    expect(useCvBuilderLink.getState().liveTurns["cv:cv-a"]).toBeUndefined();
    expect(useCvBuilderLink.getState().liveTurns["cv:cv-b"]).toEqual(b);
    act(() => {
      useCvBuilderLink.getState().applyTurnTrace("cv-a", null);
    });
    expect(useCvBuilderLink.getState().liveTurns["cv:cv-b"]).toEqual(b);
  });

  it("mode is by default null and the card hides empty CVs", () => {
    render(
      <MemoryRouter initialEntries={["/cv/cv-404"]}>
        <CopilotActivityCard cvId="cv-404" />
      </MemoryRouter>,
    );
    expect(screen.queryByTestId("cv-copilot-activity")).not.toBeInTheDocument();
  });

  it("shows the running turn on the builder surface with the dock closed", async () => {
    const { callbacks, finish } = pendingStream();
    renderSurface();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await sendSurface(user);
    await act(async () => {
      callbacks.onFlowEvent?.({
        event: "node_started",
        payload: { id: "generate", label: "Planning changes" },
      });
      callbacks.onFlowEvent?.({
        event: "tool_call",
        payload: {
          id: "get_builder_state-0",
          name: "get_builder_state",
          title: "Reading the draft",
          status: "done",
          args: '{"cv_id": "cv-1"}',
          result: "3 blocks",
          duration_ms: 210,
        },
      });
    });
    await vi.advanceTimersByTimeAsync(40);
    expect(screen.getByTestId("cv-copilot-activity")).toBeInTheDocument();
    expect(screen.getAllByText("Planning changes").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Reading the draft").length).toBeGreaterThan(0);
    expect(screen.getByTestId("cv-copilot-running")).toBeInTheDocument();
    expect(screen.getByTestId("cv-copilot-activity").dataset.active).toBe("live");
    await act(async () => {
      finish();
    });
    await vi.advanceTimersByTimeAsync(0);
  });

  it("after the turn lands the card flips to the persisted final trace", async () => {
    const { callbacks, finish } = pendingStream();
    api.fetchMessages.mockResolvedValue([
      { id: "m1", role: "user", content: "tighten summary", metadata_json: null, created_at: "2026-09-11T09:00:00Z" },
      {
        id: "m2",
        role: "assistant",
        content: "Tightened the summary.",
        metadata_json: persistedTrace,
        created_at: "2026-09-11T09:00:05Z",
      },
    ]);
    renderSurface();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await sendSurface(user);
    await act(async () => {
      callbacks.onFlowEvent?.({
        event: "node_started",
        payload: { id: "generate", label: "Planning changes" },
      });
    });
    await vi.advanceTimersByTimeAsync(40);
    expect(screen.getByTestId("cv-copilot-activity").dataset.active).toBe("live");
    await act(async () => {
      finish();
    });
    await vi.advanceTimersByTimeAsync(60);
    await waitFor(() => {
      expect(screen.getByTestId("cv-copilot-activity").dataset.active).toBe("final");
    });
    expect(screen.getByText("Reading the builder state")).toBeInTheDocument();
    expect(screen.getAllByText("Planning changes").length).toBeGreaterThan(0);
    expect(screen.getByTestId("cv-copilot-done")).toBeInTheDocument();
    expect(screen.getAllByText("Reading the draft").length).toBeGreaterThan(0);
    expect(useCvBuilderLink.getState().liveTurns["cv:cv-1"]).toBeUndefined();
  });

  it("a builder turn that produced a version links back to CV Studio from the transcript", async () => {
    useChatStore.setState({
      activeSessionId: "s-cv",
      messages: [
        { id: "m1", role: "user", content: "tighten summary", metadata_json: null, created_at: "2026-09-11T09:00:00Z" },
        {
          id: "m2",
          role: "assistant",
          content: "Tightened the summary.",
          metadata_json: { surface: "cv_builder", version: 3, nodes: [{ id: "generate", label: "Planning changes", status: "done" }] },
          created_at: "2026-09-11T09:00:05Z",
        },
      ],
    });
    renderSurface();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    await vi.advanceTimersByTimeAsync(40);
    const chip = await screen.findByTestId("chat-builder-link");
    expect(chip).toHaveAttribute("href", "/cv/cv-1");
  });
});

async function sendSurface(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
  await user.type(screen.getByRole("textbox", { name: "Message" }), "tighten summary");
  await user.keyboard("{Enter}");
  await vi.advanceTimersByTimeAsync(40);
}
