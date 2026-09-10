import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { ChatWidget } from "@/components/chat/ChatWidget";
import { useChatStore } from "@/stores/chatStore";
import type { ChatMessage } from "@/types";
import * as uniApi from "@/api/universities";
import type { ChatStreamCallbacks } from "@/api/chatStream";

const streamChatMessage = vi.hoisted(() => vi.fn());
const streamChatEdit = vi.hoisted(() => vi.fn());
const streamChatRegenerate = vi.hoisted(() => vi.fn());

vi.mock("@/api/chatStream", () => ({
  streamChatMessage: streamChatMessage,
  streamChatEdit: streamChatEdit,
  streamChatRegenerate: streamChatRegenerate,
  streamChatRequest: vi.fn(),
}));

vi.mock("@/api/universities", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/universities")>();
  return {
    ...actual,
    fetchChatSessions: vi.fn(async () => []),
    fetchMessages: vi.fn(async () => []),
    createChatSession: vi.fn(async () => ({
      id: "s1",
      title: "New chat",
      context: null,
      created_at: "2026-09-06T10:00:00Z",
    })),
    selectChatMessage: vi.fn(async () => []),
    fetchChatTree: vi.fn(async () => ({
      active_root_id: "u1",
      nodes: [
        { id: "u1", role: "user", excerpt: "find jobs", parent_id: null, children: ["a1", "a2"], active_child_id: "a2" },
        { id: "a1", role: "assistant", excerpt: "v1", parent_id: "u1", children: [], active_child_id: null },
        { id: "a2", role: "assistant", excerpt: "v2", parent_id: "u1", children: [], active_child_id: null },
      ],
    })),
  };
});

function branchedMessages(): ChatMessage[] {
  return [
    { id: "u1", role: "user", content: "find jobs", parent_id: null, variant_index: 1, variant_count: 1, sibling_ids: ["u1"], metadata_json: null, created_at: "2026-09-06T09:00:00Z" },
    { id: "a2", role: "assistant", content: "second answer", parent_id: "u1", variant_index: 2, variant_count: 2, sibling_ids: ["a1", "a2"], metadata_json: null, created_at: "2026-09-06T09:00:05Z" },
  ];
}

function pending(streamMock: ReturnType<typeof vi.fn>) {
  const callbacks = {} as ChatStreamCallbacks;
  let finish: () => void = () => {};
  streamMock.mockImplementation(
    (_a: unknown, _b: unknown, cbs: ChatStreamCallbacks) => {
      Object.assign(callbacks, cbs);
      return new Promise<void>((resolve) => {
        finish = resolve;
      });
    },
  );
  return { callbacks, finish };
}

describe("ChatWidget branching UI", () => {
  beforeEach(() => {
    vi.useRealTimers();
    streamChatMessage.mockReset();
    streamChatEdit.mockReset();
    streamChatRegenerate.mockReset();
    useChatStore.setState({
      sessions: [],
      activeSessionId: "s1",
      messages: branchedMessages(),
    });
  });

  it("shows the variant switcher and selects a sibling", async () => {
    const user = userEvent.setup();
    const selectSpy = vi.spyOn(uniApi, "selectChatMessage");
    render(
      <MemoryRouter>
        <ChatWidget />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    expect(screen.getByRole("group", { name: "Message variants" })).toHaveTextContent("2/2");
    await user.click(screen.getByRole("button", { name: "Previous variant" }));
    expect(selectSpy).toHaveBeenCalledWith("a1");
  });

  it("edits a user message into a branch (save & resend)", async () => {
    const user = userEvent.setup();
    const { finish } = pending(streamChatEdit);
    render(
      <MemoryRouter>
        <ChatWidget />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const textarea = screen.getByRole("textbox", { name: "Edit message" });
    await user.clear(textarea);
    await user.type(textarea, "find nursing jobs");
    await user.click(screen.getByRole("button", { name: "Save & resend" }));
    expect(streamChatEdit).toHaveBeenCalledWith(
      "u1",
      "find nursing jobs",
      expect.anything(),
      expect.anything(),
    );
    finish();
  });

  it("regenerates an assistant answer as a new variant", async () => {
    const user = userEvent.setup();
    const { finish } = pending(streamChatRegenerate);
    render(
      <MemoryRouter>
        <ChatWidget />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    await user.click(screen.getByRole("button", { name: "Regenerate" }));
    await waitFor(() => {
      expect(streamChatRegenerate).toHaveBeenCalledWith(
        "u1",
        expect.anything(),
        expect.anything(),
      );
    });
    finish();
  });

  it("opens the branch tree rail and walks it", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <ChatWidget />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: "Open chat assistant" }));
    await user.click(screen.getByRole("button", { name: "Conversation branches" }));
    const tree = await screen.findByRole("tree", { name: "Conversation branches" });
    expect(tree).toBeInTheDocument();
    expect(screen.getAllByRole("treeitem")).toHaveLength(3);
    const items = screen.getAllByRole("treeitem");
    expect(items[0]).toHaveAttribute("aria-selected", "true");
    const offPath = items.find((item) => item.textContent?.includes("v1"));
    expect(offPath).toHaveAttribute("aria-selected", "false");
  });
});
