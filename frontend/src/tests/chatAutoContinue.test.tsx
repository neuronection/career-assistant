import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { ChatDock } from "@/components/chat/ChatWidget";
import { useChatStore } from "@/stores/chatStore";
import { useProfileProposalsStore } from "@/stores/profileProposalsStore";
import type { ChatStreamCallbacks } from "@/api/chatStream";
import type { ChatMessage, ProfileProposalCardData as CardData } from "@/types";

const streamChatMessage = vi.hoisted(() => vi.fn());
const resolveApi = vi.hoisted(() => ({
  approveProfileProposal: vi.fn(),
  rejectProfileProposal: vi.fn(),
  fetchProfileProposals: vi.fn(),
  dismissProfileProposal: vi.fn(),
}));
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
    attachments?: unknown[],
  ) => streamChatMessage(sessionId, content, callbacks, signal, attachments),
  streamChatEdit: vi.fn(),
  streamChatRegenerate: vi.fn(),
}));

vi.mock("@/api/universities", () => ({
  fetchChatSessions: api.fetchChatSessions,
  fetchMessages: api.fetchMessages,
  createChatSession: api.createChatSession,
  renameChatSession: vi.fn(),
  deleteChatSession: vi.fn(),
  fetchUniversities: vi.fn(),
  fetchUniversity: vi.fn(),
  fetchUniversityPathways: vi.fn(),
  fetchChatContext: vi.fn(),
}));

vi.mock("@/api/ai", () => ({
  fetchAiTools: vi.fn(),
  transcribeAudio: vi.fn(),
  classifyDictationError: vi.fn(),
}));

vi.mock("@/api/cv", () => ({ fetchCvs: vi.fn().mockResolvedValue([]) }));

vi.mock("@/api/profileProposals", () => ({
  approveProfileProposal: (...args: unknown[]) =>
    resolveApi.approveProfileProposal(...args),
  rejectProfileProposal: (...args: unknown[]) =>
    resolveApi.rejectProfileProposal(...args),
  fetchProfileProposals: () => resolveApi.fetchProfileProposals(),
  dismissProfileProposal: vi.fn(),
}));

const CARD: CardData = {
  id: "prop-1",
  kind: "experience_item",
  action: "create",
  status: "pending",
  title: "Add experience · Desktop Assistant",
  entity_id: null,
  entity_label: "Desktop Assistant",
  diff: [
    {
      field: "title",
      label: "Title",
      before: null,
      after: "Desktop Assistant",
    },
  ],
  destructive: false,
  source: "chat",
  chat_session_id: "s1",
  created_at: "2026-09-15T12:00:00Z",
};

function seedTranscript(userContent: string) {
  const messages: ChatMessage[] = [
    {
      id: "u1",
      role: "user",
      content: userContent,
      parent_id: null,
      metadata_json: {},
      created_at: "2026-09-15T11:00:00Z",
    },
    {
      id: "a1",
      role: "assistant",
      content: "Prepared a proposal card for review.",
      parent_id: "u1",
      metadata_json: { proposals: [CARD] },
      created_at: "2026-09-15T11:01:00Z",
    },
  ];
  useChatStore.setState({ messages });
}

function resetStores() {
  useChatStore.setState({
    sessions: [
      {
        id: "s1",
        title: "S",
        context: null,
        created_at: "2026-09-15T12:00:00Z",
        last_activity_at: "2026-09-15T12:00:00Z",
      },
    ],
    activeSessionId: "s1",
    messages: [],
  });
  useProfileProposalsStore.setState({
    live: [],
    overrides: {},
    pendingCount: 0,
    pendingBySession: { s1: 1 },
    lastResolved: null,
    lastFollowupKey: null,
  });
}

function mount() {
  return render(
    <MemoryRouter initialEntries={["/chat"]}>
      <ChatDock />
    </MemoryRouter>,
  );
}

function mockApprove() {
  resolveApi.approveProfileProposal.mockResolvedValue({
    proposal: { ...CARD, status: "approved" },
    applied: { id: "item-1", kind: "experience_item", label: "AI Launcher" },
    already: false,
  });
}

describe("auto-continue after resolving proposal cards", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStores();
    streamChatMessage.mockResolvedValue(undefined);
    api.fetchChatSessions.mockResolvedValue([
      {
        id: "s1",
        title: "S",
        context: null,
        created_at: "2026-09-15T12:00:00Z",
        last_activity_at: "2026-09-15T12:00:00Z",
      },
    ]);
    resolveApi.fetchProfileProposals.mockResolvedValue({
      proposals: [],
      pending_count: 0,
    });
    api.fetchMessages.mockResolvedValue([]);
  });

  it("auto-answers once when the last card of the session is approved", async () => {
    mockApprove();
    seedTranscript("build me the desktop assistant entry");
    mount();

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Approve" }));
    await waitFor(() => {
      const call = streamChatMessage.mock.calls[streamChatMessage.mock.calls.length - 1];
      expect(call?.[0]).toBe("s1");
      expect(call?.[1]).toBe(`(resolved card: ${CARD.title} — approved)`);
    });
  });

  it("never chains — no followup when the previous turn was one", async () => {
    mockApprove();
    seedTranscript("(resolved card: Add experience · Desktop Assistant — approved)");
    mount();

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Approve" }));
    await waitFor(() =>
      expect(resolveApi.approveProfileProposal).toHaveBeenCalledTimes(1),
    );
    expect(streamChatMessage).not.toHaveBeenCalled();
  });

  it("does not fire for resolutions of other sessions", async () => {
    mockApprove();
    seedTranscript("build me the desktop assistant entry");
    mount();
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Approve" }));
    // The real resolve targets s1 (fires); a later foreign-session
    // resolve event must not trigger another turn in this surface.
    await waitFor(() =>
      expect(streamChatMessage).toHaveBeenCalledTimes(1),
    );
    useProfileProposalsStore.setState({
      lastResolved: {
        id: "other",
        sessionId: "other",
        title: "X",
        action: "approve",
        status: "approved",
      },
    });
    expect(streamChatMessage).toHaveBeenCalledTimes(1);
  });
});
