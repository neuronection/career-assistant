import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Link, Route, Routes } from "react-router-dom";

import { ChatDock, ChatWidget } from "@/components/chat/ChatWidget";
import { ChatPage } from "@/pages/ChatPage";
import { useChatStore } from "@/stores/chatStore";
import type { ChatStreamCallbacks } from "@/api/chatStream";

const streamChatMessage = vi.hoisted(() => vi.fn());
const api = vi.hoisted(() => ({
  fetchChatSessions: vi.fn(),
  fetchMessages: vi.fn(),
  createChatSession: vi.fn(),
  renameChatSession: vi.fn(),
  deleteChatSession: vi.fn(),
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
  renameChatSession: api.renameChatSession,
  deleteChatSession: api.deleteChatSession,
  fetchUniversities: vi.fn(),
  fetchUniversity: vi.fn(),
  fetchUniversityPathways: vi.fn(),
  fetchChatContext: vi.fn(),
}));

const aiApi = vi.hoisted(() => ({
  fetchAiTools: vi.fn(),
  transcribeAudio: vi.fn(),
  classifyDictationError: vi.fn(),
}));

vi.mock("@/api/ai", () => ({
  fetchAiTools: aiApi.fetchAiTools,
  transcribeAudio: aiApi.transcribeAudio,
  classifyDictationError: aiApi.classifyDictationError,
}));

function pendingStream(): { callbacks: ChatStreamCallbacks; finish: () => void } {
  const callbacks = {} as ChatStreamCallbacks;
  let finish: () => void = () => {};
  streamChatMessage.mockImplementation(
    (_id: string, _content: string, cbs: ChatStreamCallbacks) => {
      Object.assign(callbacks, cbs);
      return new Promise<void>((resolve) => {
        finish = resolve;
      });
    },
  );
  return { callbacks, finish: () => finish() };
}

function renderWidget(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ChatWidget />
    </MemoryRouter>,
  );
}

describe("ChatWidget (library surface)", () => {
  beforeEach(() => {
    vi.useRealTimers()
    useChatStore.setState({ chatMode: "bubble", bubbleOpen: false });
    streamChatMessage.mockReset();
    aiApi.fetchAiTools.mockReset().mockResolvedValue([
      {
        key: "search_jobs",
        title: "Searching the job catalog",
        description: "Full-text search over the job catalog.",
        scope: "read",
        audiences: [],
        cost_hint: null,
        requires_user: false,
        input_schema: {
          properties: {
            query: { type: "string", description: "What to look for." },
            limit: { type: "integer" },
          },
          required: ["query"],
        },
        builtin: true,
        kind: "tool",
        hitl: false,
      },
      {
        key: "propose_profile_edits",
        title: "Propose profile edits",
        description:
          "Every edit arrives as a review card you approve first — nothing is written without confirmation.",
        scope: "write",
        audiences: [],
        cost_hint: null,
        requires_user: true,
        input_schema: null,
        builtin: true,
        kind: "capability",
        hitl: true,
      },
    ]);
    aiApi.transcribeAudio.mockReset();
    aiApi.classifyDictationError.mockReset();
    api.fetchChatSessions.mockReset().mockResolvedValue([
      { id: "s1", title: "Nursing roles", context: null, created_at: "2026-09-01T10:00:00Z" },
    ]);
    api.fetchMessages.mockReset().mockResolvedValue([]);
    api.createChatSession.mockReset().mockResolvedValue({
      id: "s2",
      title: "New chat",
      context: null,
      created_at: "2026-09-06T10:00:00Z",
    });
    useChatStore.setState({ sessions: [], activeSessionId: null, messages: [], bubbleOpen: false });
  });

  it("opens the bubble to a fresh composer and starts conversations lazily", async () => {
    const user = userEvent.setup();
    renderWidget();
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    // Fresh chat: the composer is immediately usable, no history rows shown.
    expect(await screen.findByRole("textbox", { name: "Message" })).toBeInTheDocument();
    expect(screen.queryByText("Nursing roles")).not.toBeInTheDocument();
    // "New chat" is a client-side reset — no session row until a message is sent.
    await user.click(screen.getByRole("button", { name: "New chat" }));
    expect(useChatStore.getState().activeSessionId).toBeNull();
    expect(api.createChatSession).not.toHaveBeenCalled();
  });

  it("closes the bubble from the header close (no overlaid launcher close)", async () => {
    const user = userEvent.setup();
    renderWidget();
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    const panel = await screen.findByRole("complementary", { name: "Open chat assistant" });
    // exactly one close affordance, and it lives in the panel header
    expect(within(panel).getAllByRole("button", { name: "Close panel" })).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Close panel" }));
    expect(screen.queryByRole("complementary", { name: "Open chat assistant" })).not.toBeInTheDocument();
  });

  it("sends a message and streams the markdown reply live", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    useChatStore.setState({ activeSessionId: "s1", messages: [] });
    const { callbacks } = pendingStream();
    renderWidget();
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    const input = screen.getByRole("textbox", { name: "Message" });
    await user.type(input, "what is a nurse?");
    await user.keyboard("{Enter}");
    expect(streamChatMessage).toHaveBeenCalledWith(
      "s1",
      "what is a nurse?",
      expect.anything(),
      expect.anything(),
    );
    callbacks.onDelta?.("**Nurses** care for patients");
    await vi.advanceTimersByTimeAsync(40);
    await vi.advanceTimersByTimeAsync(0);
    expect(await screen.findByText("Nurses", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("care for patients", { exact: false })).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("renders persisted messages as markdown with reference chips", async () => {
    useChatStore.setState({
      activeSessionId: "s1",
      messages: [
        { id: "m1", role: "user", content: "find nursing jobs", metadata_json: null, created_at: "2026-09-06T09:00:00Z" },
        {
          id: "m2",
          role: "assistant",
          content: "Here are **matches**:\n\n```json\n{\"count\": 2}\n```",
          metadata_json: {
            referenced_job_codes: ["NO-1210"],
            referenced_posting_refs: ["REF-9"],
            explore_query: "q=nurse",
          },
          created_at: "2026-09-06T09:00:05Z",
        },
      ],
    });
    renderWidget();
    await userEvent.click(screen.getByRole("button", { name: "Open chat assistant" }));
    expect(screen.getByText("matches")).toBeInTheDocument();
    expect(screen.getByText("json")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy code" })).toBeInTheDocument();
    expect(screen.getByText("NO-1210").closest("a")).toHaveAttribute("href", "/jobs/NO-1210");
    expect(screen.getByTestId("chat-posting-ref-REF-9")).toBeInTheDocument();
    expect(screen.getByTestId("chat-explore-link")).toBeInTheDocument();
  });

  it("stops the in-flight turn from the composer", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    useChatStore.setState({ activeSessionId: "s1", messages: [] });
    const { callbacks } = pendingStream();
    renderWidget();
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    await user.type(screen.getByRole("textbox", { name: "Message" }), "hello");
    await user.keyboard("{Enter}");
    callbacks.onDelta?.("partial answer");
    await vi.advanceTimersByTimeAsync(40);
    await vi.advanceTimersByTimeAsync(0);
    const stop = await screen.findByRole("button", { name: "Stop generating" });
    await user.click(stop);
    // Interrupted turns persist server-side now: the surface
    // refreshes the transcript and returns the composer to send state.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Send message" })).toBeInTheDocument();
    });
    expect(api.fetchMessages).toHaveBeenCalledWith("s1");
    vi.useRealTimers();
  });

  it("hides the launcher on the full chat page", () => {
    renderWidget("/chat");
    expect(screen.queryByRole("button", { name: "Open chat assistant" })).not.toBeInTheDocument();
  });

  it("renders completed tool cards in the live tail", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    useChatStore.setState({ activeSessionId: "s1", messages: [] });
    const { callbacks } = pendingStream();
    renderWidget();
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    await user.type(screen.getByRole("textbox", { name: "Message" }), "nurse jobs");
    await user.keyboard("{Enter}");
    callbacks.onFlowEvent?.({
      event: "tool_call",
      payload: {
        id: "search_jobs-0",
        name: "search_jobs",
        title: "Searching the job catalog",
        status: "done",
        args: '{"query": "nurse"}',
        result: '["NO-1210"]',
        duration_ms: 12,
      },
    });
    await vi.advanceTimersByTimeAsync(40);
    await vi.advanceTimersByTimeAsync(0);
    expect(await screen.findByTestId("chat-live-tools")).toBeInTheDocument();
    expect(screen.getByText("Searching the job catalog")).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("renders the turn trace as meta badges on assistant messages", async () => {
    useChatStore.setState({
      activeSessionId: "s1",
      messages: [
        { id: "m1", role: "user", content: "find nursing jobs", metadata_json: null, created_at: "2026-09-06T09:00:00Z" },
        {
          id: "m2",
          role: "assistant",
          content: "Here you go.",
          metadata_json: {
            model: "gpt-5.6",
            elapsed_ms: 1930,
            tools: [{ name: "search_jobs", duration_ms: 12, results: ["NO-1210"] }],
            referenced_job_codes: ["NO-1210"],
          },
          created_at: "2026-09-06T09:00:05Z",
        },
      ],
    });
    renderWidget();
    await userEvent.click(screen.getByRole("button", { name: "Open chat assistant" }));
    const badges = screen.getByTestId("chat-meta-badges");
    expect(badges).toHaveTextContent("gpt-5.6");
    expect(badges).toHaveTextContent("1.9 s");
    expect(badges).toHaveTextContent("1 tool");
  });

  it("renders the trace timeline as the single persisted trace surface", async () => {
    useChatStore.setState({
      activeSessionId: "s1",
      messages: [
        { id: "m1", role: "user", content: "find nursing jobs", metadata_json: null, created_at: "2026-09-06T09:00:00Z" },
        {
          id: "m2",
          role: "assistant",
          content: "Here you go.",
          metadata_json: {
            model: "gpt-5.6",
            elapsed_ms: 1930,
            tokens_out: 210,
            tools: [
              {
                name: "search_jobs",
                title: "Searching the job catalog",
                status: "done",
                start_ms: 0,
                duration_ms: 12,
                args_summary: '{"query": "nursing"}',
                result_summary: '["NO-1210"]',
                results: ["NO-1210"],
              },
            ],
            nodes: [
              { id: "ground", label: "searching the catalog", status: "done", start_ms: 0, duration_ms: 40 },
              { id: "generate", label: "writing the reply", status: "done", start_ms: 45, duration_ms: 1880 },
            ],
            referenced_job_codes: ["NO-1210"],
          },
          created_at: "2026-09-06T09:00:05Z",
        },
      ],
    });
    const user = userEvent.setup();
    renderWidget();
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    const trace = await screen.findByTestId("chat-message-trace");
    expect(trace).toBeInTheDocument();
    expect(screen.queryByText("Searching the job catalog")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show response trace" }));
    expect(screen.getByText("Total 1.9 s")).toBeInTheDocument();
    expect(screen.getByText("210 tokens")).toBeInTheDocument();
    expect(screen.getByText("writing the reply")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "search_jobs details" }));
    expect(await screen.findByText("query")).toBeInTheDocument();
    expect(screen.getByText("nursing")).toBeInTheDocument();
    expect(screen.queryByText(/"query": "nursing"/)).not.toBeInTheDocument();
  });

  it("renders the builder copilot's persisted trace with expandable tool details", async () => {
    useChatStore.setState({
      activeSessionId: "s1",
      messages: [
        { id: "m1", role: "user", content: "switch template", metadata_json: null, created_at: "2026-09-11T09:00:00Z" },
        {
          id: "m2",
          role: "assistant",
          content: "Switched the template.",
          metadata_json: {
            surface: "cv_builder",
            model: "gpt-5.6",
            elapsed_ms: 2100,
            version: 2,
            operations: [{ op: "set_template", ok: true, detail: "template “ATS Classic”" }],
            tools: [
              {
                name: "cv_read_state",
                title: "Reading the builder state",
                status: "done",
                start_ms: 0,
                duration_ms: 35,
                args_summary: "templates, blocks, sources, metrics, lint",
                result_summary: "6 blocks · 4 sources · 1 page(s)",
              },
              {
                name: "cv_set_template",
                title: "Switching template",
                status: "done",
                start_ms: 1240,
                duration_ms: 120,
                args_summary: '{"template_id": "abc"}',
                result_summary: "template “ATS Classic”",
              },
            ],
            nodes: [
              { id: "ground", label: "reading the builder state", status: "done", start_ms: 0, duration_ms: 35 },
              { id: "plan", label: "planning changes", status: "done", start_ms: 36, duration_ms: 1200 },
              { id: "apply", label: "applying changes", status: "done", start_ms: 1240, duration_ms: 800 },
            ],
          },
          created_at: "2026-09-11T09:00:05Z",
        },
      ],
    });
    const user = userEvent.setup();
    renderWidget();
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    const trace = await screen.findByTestId("chat-message-trace");
    expect(trace).toBeInTheDocument();
    expect(screen.queryByText("Reading the builder state")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show response trace" }));
    expect(screen.getByText("planning changes")).toBeInTheDocument();
    expect(screen.getByText("applying changes")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "cv_read_state details" }));
    expect(screen.getByText("templates, blocks, sources, metrics, lint")).toBeInTheDocument();
    expect(screen.getByText("6 blocks · 4 sources · 1 page(s)")).toBeInTheDocument();
  });

  it("offers empty-state suggestions that seed the draft", async () => {
    const user = userEvent.setup();
    renderWidget();
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    await user.click(screen.getByRole("button", { name: "New chat" }));
    const input = await screen.findByRole("textbox", { name: "Message" });
    await user.click(screen.getAllByTestId("chat-suggestion")[0]);
    expect(input).toHaveValue("Find entry-level roles that fit my profile");
  });

  it("renames and deletes sessions from the row actions", async () => {
    api.renameChatSession.mockReset().mockResolvedValue(undefined);
    api.deleteChatSession.mockReset().mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderWidget();
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    await user.click(await screen.findByRole("button", { name: "Chat history" }));
    await screen.findByText("Nursing roles");

    await user.click(screen.getByRole("button", { name: "Rename" }));
    const input = await screen.findByTestId("session-rename-input");
    await user.clear(input);
    await user.type(input, "ICU rotations");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(api.renameChatSession).toHaveBeenCalledWith("s1", "ICU rotations");
    });
    expect(await screen.findByText("ICU rotations")).toBeInTheDocument();
    expect(useChatStore.getState().sessions[0].title).toBe("ICU rotations");

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(await screen.findByRole("button", { name: "Delete chat" }));
    await waitFor(() => {
      expect(api.deleteChatSession).toHaveBeenCalledWith("s1");
    });
    expect(screen.queryByText("ICU rotations")).not.toBeInTheDocument();
    expect(useChatStore.getState().activeSessionId).toBeNull();
  });

  it("hides the mic when speech input is unavailable", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    useChatStore.setState({ activeSessionId: "s1", messages: [] });
    renderWidget();
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    const dictate = await screen.findByRole("button", { name: "Dictate" });
    await user.click(dictate);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Dictate" })).not.toBeInTheDocument();
    });
    vi.useRealTimers();
  });

  it("opens the available-tools catalog from the chat header", async () => {
    const user = userEvent.setup();
    renderWidget();
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    await user.click(await screen.findByRole("button", { name: "Available tools" }));
    const dialog = await screen.findByTestId("chat-tools-dialog");
    expect(dialog).toHaveTextContent("Tools the assistant can use");
    expect(aiApi.fetchAiTools).toHaveBeenCalledWith({ includeCapabilities: true });
    expect(await screen.findByText("search_jobs")).toBeInTheDocument();
    expect(screen.getByText("Searching the job catalog")).toBeInTheDocument();
    expect(screen.getByText("read")).toBeInTheDocument();

    await user.click(screen.getByText("search_jobs"));
    expect(screen.getByText("Full-text search over the job catalog.")).toBeInTheDocument();
    expect(screen.getByText("query")).toBeInTheDocument();
    expect(screen.getByText(/What to look for\./)).toBeInTheDocument();
    expect(screen.getByText(/optional/)).toBeInTheDocument();
  });

  it("badges the HITL capability row and hides its scope chip", async () => {
    const user = userEvent.setup();
    renderWidget();
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    await user.click(await screen.findByRole("button", { name: "Available tools" }));
    await screen.findByTestId("chat-tools-dialog");

    expect(await screen.findByText("propose_profile_edits")).toBeInTheDocument();
    expect(screen.getByText("HITL action")).toBeInTheDocument();
    expect(screen.queryByText("write")).not.toBeInTheDocument();
  });

  it("switches chats from the header history popover", async () => {
    api.fetchChatSessions.mockResolvedValue([
      { id: "s1", title: "Nursing roles", context: null, created_at: "2026-09-01T10:00:00Z" },
      {
        id: "s9",
        title: "Portfolio review",
        context: null,
        created_at: "2026-09-05T10:00:00Z",
        last_activity_at: "2026-09-06T08:30:00Z",
      },
    ]);
    api.fetchMessages.mockReset().mockResolvedValue([]);
    useChatStore.setState({ activeSessionId: "s1", messages: [] });
    const user = userEvent.setup();
    renderWidget();
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    await screen.findByRole("textbox", { name: "Message" });

    await user.click(screen.getByRole("button", { name: "Chat history" }));
    const listed = await screen.findByText("Portfolio review");
    expect(listed).toBeInTheDocument();

    await user.click(listed);
    await waitFor(() => {
      expect(useChatStore.getState().activeSessionId).toBe("s9");
    });
    expect(api.fetchMessages).toHaveBeenCalledWith("s9");
    await waitFor(() => {
      expect(screen.queryByText("Portfolio review")).not.toBeInTheDocument();
    });
  });
});

describe("opt-in bubble launcher (plan 75)", () => {
  beforeEach(() => {
    localStorage.clear();
    useChatStore.setState({
      sessions: [],
      activeSessionId: null,
      messages: [],
      chatMode: "docked",
    });
  });

  it("does not render the launcher in docked mode (the default)", () => {
    renderWidget();
    expect(screen.queryByRole("button", { name: "Open chat assistant" })).not.toBeInTheDocument();
  });

  it("renders the launcher only after the user opts into bubble mode", () => {
    useChatStore.getState().setChatMode("bubble");
    renderWidget();
    expect(screen.getByRole("button", { name: "Open chat assistant" })).toBeInTheDocument();
  });

  it("persists the chosen mode across store reads (ca:chat:mode)", () => {
    useChatStore.getState().setChatMode("bubble");
    expect(localStorage.getItem("ca:chat:mode")).toBe("bubble");
    useChatStore.getState().setChatMode("docked");
    expect(localStorage.getItem("ca:chat:mode")).toBe("docked");
  });

  it("opens the launcher again from the docked close button", async () => {
    const user = userEvent.setup();
    const { ChatDock } = await import("@/components/chat/ChatWidget");
    render(
      <MemoryRouter>
        <ChatDock />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: "Close panel" }));
    expect(useChatStore.getState().chatMode).toBe("bubble");
  });

  it("stays width-aware: page floor above lg, full-screen overlay below lg", async () => {
    const { ChatDock } = await import("@/components/chat/ChatWidget");
    render(
      <MemoryRouter>
        <ChatDock />
      </MemoryRouter>,
    );
    const dock = screen.getByTestId("chat-dock");
    expect(dock.className).toContain("lg:max-w-[calc(100vw-36rem)]");
    expect(dock.className).toContain("max-lg:fixed");
    expect(dock.className).toContain("max-lg:inset-0");
    expect(dock.className).toContain("max-lg:!w-full");
    expect(screen.getByTestId("chat-dock-resize-handle").className).toContain(
      "max-lg:hidden"
    );
  });
});

describe("opening the chat page takes over overlay surfaces", () => {
  beforeEach(() => {
    vi.useRealTimers();
    localStorage.clear();
    api.fetchChatSessions.mockReset().mockResolvedValue([]);
    api.fetchMessages.mockReset().mockResolvedValue([]);
    useChatStore.setState({
      sessions: [],
      activeSessionId: "s1",
      messages: [],
      chatMode: "docked",
      bubbleOpen: false,
    });
  });

  function renderShell() {
    function Shell() {
      const chatMode = useChatStore((state) => state.chatMode);
      return (
        <>
          <Routes>
            <Route
              path="/chat"
              element={
                <div data-testid="chat-page">
                  <ChatPage />
                </div>
              }
            />
            <Route path="*" element={<div data-testid="other-page" />} />
          </Routes>
          {chatMode === "docked" && <ChatDock />}
          <ChatWidget />
          <nav>
            <Link to="/chat">Open chat page</Link>
            <Link to="/">Leave chat page</Link>
          </nav>
        </>
      );
    }
    return render(
      <MemoryRouter initialEntries={["/"]}>
        <Shell />
      </MemoryRouter>,
    );
  }

  it("closes an expanded bubble and hands its conversation to the page", async () => {
    const user = userEvent.setup();
    useChatStore.getState().setChatMode("bubble");
    renderShell();
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    await screen.findByRole("textbox", { name: "Message" });
    expect(useChatStore.getState().bubbleOpen).toBe(true);

    await user.click(screen.getByText("Open chat page"));

    expect(
      screen.queryByRole("complementary", { name: "Open chat assistant" })
    ).not.toBeInTheDocument();
    expect(useChatStore.getState().bubbleOpen).toBe(false);
    // The page opens the same conversation — the shared session survives.
    expect(useChatStore.getState().activeSessionId).toBe("s1");

    await user.click(screen.getByText("Leave chat page"));
    expect(useChatStore.getState().chatMode).toBe("bubble");
    expect(
      screen.queryByRole("complementary", { name: "Open chat assistant" })
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open chat assistant" })).toBeInTheDocument();
  });

  it("closes the dock on the page and restores it with the same conversation after leaving", async () => {
    const user = userEvent.setup();
    renderShell();
    expect(screen.getByTestId("chat-dock")).toBeInTheDocument();

    await user.click(screen.getByText("Open chat page"));
    expect(screen.queryByTestId("chat-dock")).not.toBeInTheDocument();
    expect(useChatStore.getState().chatMode).toBe("docked");
    expect(useChatStore.getState().activeSessionId).toBe("s1");

    await user.click(screen.getByText("Leave chat page"));
    expect(screen.getByTestId("chat-dock")).toBeInTheDocument();
    expect(useChatStore.getState().activeSessionId).toBe("s1");
  });

  it("opens the floating window when the popup switcher leaves the page", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByText("Open chat page"));
    await user.click(within(screen.getByTestId("chat-page")).getByTestId("chat-view-popup"));

    expect(screen.getByTestId("other-page")).toBeInTheDocument();
    expect(useChatStore.getState().chatMode).toBe("bubble");
    // The explicit popup choice expands the floating window, not just the FAB.
    expect(useChatStore.getState().bubbleOpen).toBe(true);
    expect(
      await screen.findByRole("complementary", { name: "Open chat assistant" })
    ).toBeInTheDocument();
    expect(useChatStore.getState().activeSessionId).toBe("s1");
  });
});
