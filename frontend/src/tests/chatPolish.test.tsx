import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { ChatWidget } from "@/components/chat/ChatWidget";
import { useCareerChatContext, CareerChatProvider } from "@/components/chat/useCareerChat";
import { buildChatMarkdownFromRows } from "@/components/chat/exportChat";
import { getDraft, writeDraft } from "@/components/chat/drafts";
import { useChatStore } from "@/stores/chatStore";
import type { ChatStreamCallbacks } from "@/api/chatStream";

const streamChatMessage = vi.hoisted(() => vi.fn());
const streamChatRegenerate = vi.hoisted(() => vi.fn());
const api = vi.hoisted(() => ({
  fetchChatSessions: vi.fn(),
  fetchMessages: vi.fn(),
  createChatSession: vi.fn(),
  selectChatMessage: vi.fn(),
}));

vi.mock("@/api/chatStream", () => ({
  streamChatMessage: streamChatMessage,
  streamChatEdit: vi.fn(),
  streamChatRegenerate: streamChatRegenerate,
  streamChatRequest: vi.fn(),
}));

vi.mock("@/api/universities", () => ({
  fetchChatSessions: api.fetchChatSessions,
  fetchMessages: api.fetchMessages,
  createChatSession: api.createChatSession,
  selectChatMessage: api.selectChatMessage,
  fetchChatTree: vi.fn(),
}));

describe("drafts", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("round-trips per session and clears on demand", () => {
    expect(getDraft("s1")).toBe("");
    writeDraft("s1", "half-written question");
    expect(getDraft("s1")).toBe("half-written question");
    expect(getDraft("s2")).toBe("");
    writeDraft("s1", "");
    expect(getDraft("s1")).toBe("");
  });

  it("ignores null sessions", () => {
    writeDraft(null, "orphan");
    expect(getDraft(null)).toBe("");
  });

  it("survives a page reload simulation", () => {
    writeDraft("s1", "persistent");
    expect(getDraft("s1")).toBe("persistent");
  });
});

describe("export as markdown", () => {
  it("builds a markdown transcript with references", () => {
    const markdown = buildChatMarkdownFromRows("Nursing roles", [
      { id: "m1", role: "user", content: "find nursing jobs", metadata_json: null, created_at: "2026-09-06T09:00:00Z" },
      {
        id: "m2",
        role: "assistant",
        content: "Here are **matches**.",
        metadata_json: { referenced_job_codes: ["NO-1210"], referenced_posting_refs: ["REF-9"] },
        created_at: "2026-09-06T09:00:05Z",
      },
    ]);
    expect(markdown).toContain("# Nursing roles");
    expect(markdown).toContain("**You:**");
    expect(markdown).toContain("find nursing jobs");
    expect(markdown).toContain("**Career Assistant:**");
    expect(markdown).toContain("Here are **matches**.");
    expect(markdown).toContain("jobs: NO-1210 · postings: REF-9");
  });
});

function RetryProbe() {
  const chat = useCareerChatContext();
  return (
    <div>
      <button type="button" onClick={() => void chat.retry()}>
        retry-now
      </button>
      <span data-status={chat.stream.status} />
    </div>
  );
}

describe("retry of failed turns", () => {
  beforeEach(() => {
    vi.useRealTimers();
    streamChatMessage.mockReset();
    streamChatRegenerate.mockReset();
    api.fetchMessages.mockReset().mockResolvedValue([]);
    api.fetchChatSessions.mockReset().mockResolvedValue([]);
    api.createChatSession.mockReset().mockResolvedValue({
      id: "s1",
      title: "New chat",
      context: null,
      created_at: "2026-09-06T10:00:00Z",
    });
    useChatStore.setState({
      sessions: [],
      activeSessionId: "s1",
      messages: [
        { id: "u1", role: "user", content: "find jobs", parent_id: null, variant_index: 1, variant_count: 1, sibling_ids: ["u1"], metadata_json: null, created_at: "2026-09-06T09:00:00Z" },
      ],
    });
  });

  it("surfaces a retryable error and retries via the regenerate path", async () => {
    const user = userEvent.setup();
    streamChatMessage.mockImplementation(
      (_id: unknown, _content: unknown, callbacks: ChatStreamCallbacks) => {
        callbacks.onFlowEvent?.({
          event: "flow_failed",
          payload: { code: "rate_limit", message: "slow down", retryable: true },
        });
        return Promise.reject(new Error("rate limited"));
      },
    );
    const { callbacks } = {
      callbacks: {} as ChatStreamCallbacks,
    };
    streamChatRegenerate.mockImplementation(
      (_id: unknown, cbs: ChatStreamCallbacks) => Object.assign(callbacks, cbs),
    );

    render(
      <MemoryRouter>
        <ChatWidget />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    await user.type(screen.getByRole("textbox", { name: "Message" }), "hello");
    await user.keyboard("{Enter}");

    const retryButton = await screen.findByRole("button", { name: "Retry" });
    expect(screen.getByRole("alert")).toHaveTextContent("rate_limit");

    streamChatMessage.mockReset();
    await user.click(retryButton);
    await waitFor(() => {
      expect(streamChatRegenerate).toHaveBeenCalled();
    });
    expect(streamChatRegenerate.mock.calls[0]?.[0]).toBe("u1");
  });

  it("exposes retry through the shared context hook", async () => {
    const user = userEvent.setup();
    streamChatRegenerate.mockResolvedValue(undefined);
    render(
      <MemoryRouter>
        <CareerChatProvider>
          <RetryProbe />
        </CareerChatProvider>
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: "retry-now" }));
    await waitFor(() => {
      expect(streamChatRegenerate).toHaveBeenCalled();
    });
    expect(streamChatRegenerate.mock.calls[0]?.[0]).toBe("u1");
  });
});
