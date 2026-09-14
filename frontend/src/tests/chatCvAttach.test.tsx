import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { ChatDock } from "@/components/chat/ChatWidget";
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
const cvApi = vi.hoisted(() => ({ fetchCvs: vi.fn() }));

vi.mock("@/api/chatStream", () => ({
  streamChatMessage: (
    sessionId: string,
    content: string,
    callbacks: ChatStreamCallbacks,
    signal?: AbortSignal,
    attachments?: unknown[],
  ) =>
    streamChatMessage(sessionId, content, callbacks, signal, attachments),
  streamChatEdit: vi.fn(),
  streamChatRegenerate: vi.fn(),
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

vi.mock("@/api/ai", () => ({
  fetchAiTools: vi.fn(),
  transcribeAudio: vi.fn(),
  classifyDictationError: vi.fn(),
}));

vi.mock("@/api/cv", () => ({
  fetchCvs: cvApi.fetchCvs,
}));

function seedStore() {
  useChatStore.setState({
    sessions: [
      {
        id: "s1",
        title: "Session",
        context: null,
        created_at: "2026-09-14T12:00:00Z",
        last_activity_at: "2026-09-14T12:00:00Z",
      },
    ],
    activeSessionId: "s1",
    messages: [],
  });
}

const CVS = [
  { id: "cv-1", title: "Backend CV" },
  { id: "cv-2", title: "Design CV" },
];

function mount(route = "/chat") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <ChatDock />
    </MemoryRouter>,
  );
}

describe("CV reference attachments (plan 78.3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    seedStore();
    streamChatMessage.mockResolvedValue(undefined);
    cvApi.fetchCvs.mockResolvedValue(CVS);
    api.fetchMessages.mockResolvedValue([]);
  });

  it("suggests the open Studio CV and attaches on click", async () => {
    const user = userEvent.setup();
    mount("/cv/cv-1");
    const suggested = await screen.findByTestId("chat-attach-cv");
    expect(suggested).toHaveTextContent("Reference: Backend CV");
    await user.click(suggested);
    expect(screen.getByTestId("chat-attachment-cv-1")).toHaveTextContent(
      "Backend CV",
    );
  });

  it("attaches any CV through the popover and caps at two", async () => {
    const user = userEvent.setup();
    mount("/chat");
    await user.click(screen.getByTestId("chat-attach-open"));
    await screen.findByTestId("chat-attach-cv-cv-1");
    await user.click(screen.getByTestId("chat-attach-cv-cv-1"));
    await user.click(screen.getByTestId("chat-attach-open"));
    await user.click(screen.getByTestId("chat-attach-cv-cv-2"));
    expect(screen.getByTestId("chat-attachment-cv-1")).toBeInTheDocument();
    expect(screen.getByTestId("chat-attachment-cv-2")).toBeInTheDocument();
    expect(screen.queryByTestId("chat-attach-open")).not.toBeInTheDocument();
  });

  it("sends attachments with the message and clears them", async () => {
    const user = userEvent.setup();
    mount("/chat");
    await user.click(screen.getByTestId("chat-attach-open"));
    await screen.findByTestId("chat-attach-cv-cv-1");
    await user.click(screen.getByTestId("chat-attach-cv-cv-1"));

    const composer = screen.getByRole("textbox", { name: "Message" });
    await user.type(composer, "review this");
    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(streamChatMessage).toHaveBeenCalledWith(
        "s1",
        "review this",
        expect.anything(),
        expect.anything(),
        [{ kind: "cv", cv_id: "cv-1" }],
      ),
    );
    expect(
      screen.queryByTestId("chat-attachment-cv-1"),
    ).not.toBeInTheDocument();
  });

  it("renders attachment and reference chips on messages", async () => {
    useChatStore.setState({
      messages: [
        {
          id: "u1",
          role: "user",
          content: "review this",
          created_at: "2026-09-14T12:00:00Z",
          metadata_json: {
            attachments: [{ kind: "cv", cv_id: "cv-1", title: "Backend CV" }],
          },
        },
        {
          id: "a1",
          role: "assistant",
          content: "grounded answer",
          parent_id: "u1",
          created_at: "2026-09-14T12:00:01Z",
          metadata_json: { referenced_cv_ids: ["cv-1"] },
        },
      ],
    });
    mount("/chat");
    const chips = await screen.findAllByTestId("cv-ref-chip-cv-1");
    expect(chips.length).toBe(2);
    for (const chip of chips) {
      expect(chip).toHaveTextContent("Backend CV");
      expect(chip).toHaveAttribute("href", "/cv/cv-1");
    }
  });
});
