import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useNavigate } from "react-router-dom";

import { ChatDock } from "@/components/chat/ChatWidget";
import { openCvChat } from "@/components/chat/cvChatLink";
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
    sessions: [SESSION],
    activeSessionId: "s1",
    messages: [],
    attachments: [],
    pendingCvAttach: null,
  });
}

const CVS = [
  { id: "cv-1", title: "Backend CV" },
  { id: "cv-2", title: "Design CV" },
];

const SESSION = {
  id: "s1",
  title: "Session",
  context: null,
  created_at: "2026-09-14T12:00:00Z",
  last_activity_at: "2026-09-14T12:00:00Z",
};

function mount(route = "/") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <ChatDock />
    </MemoryRouter>,
  );
}

/** Mounts with a nav probe so a test can switch the Studio route the
 * way the user does — the auto-attach effect tracks the route. */
function mountWithNav(route: string) {
  function NavProbe() {
    const navigate = useNavigate();
    return (
      <button
        data-testid="nav-cv-2"
        onClick={() => navigate("/cv/cv-2")}
      />
    );
  }
  return render(
    <MemoryRouter initialEntries={[route]}>
      <NavProbe />
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
    api.fetchChatSessions.mockResolvedValue([SESSION]);
    api.fetchMessages.mockResolvedValue([]);
  });

  it("auto-attaches the open Studio CV without asking", async () => {
    mount("/cv/cv-1");
    const chip = await screen.findByTestId("chat-attachment-cv-1");
    expect(chip).toHaveTextContent("Backend CV");
    expect(useChatStore.getState().attachments).toEqual([
      { kind: "cv", cv_id: "cv-1", title: "Backend CV", auto: true },
    ]);
  });

  it("replaces the auto reference when another CV is opened while fresh", async () => {
    mountWithNav("/cv/cv-1");
    await screen.findByTestId("chat-attachment-cv-1");
    await userEvent.click(screen.getByTestId("nav-cv-2"));
    await screen.findByTestId("chat-attachment-cv-2");
    expect(screen.queryByTestId("chat-attachment-cv-1")).not.toBeInTheDocument();
    expect(useChatStore.getState().attachments).toEqual([
      { kind: "cv", cv_id: "cv-2", title: "Design CV", auto: true },
    ]);
  });

  it("accumulates references when the conversation already started", async () => {
    useChatStore.setState({
      messages: [
        {
          id: "u0",
          role: "user",
          content: "earlier turn",
          created_at: "2026-09-14T12:00:00Z",
          metadata_json: null,
        },
      ],
    });
    mountWithNav("/cv/cv-1");
    await screen.findByTestId("chat-attachment-cv-1");
    await userEvent.click(screen.getByTestId("nav-cv-2"));
    await screen.findByTestId("chat-attachment-cv-2");
    expect(screen.getByTestId("chat-attachment-cv-1")).toBeInTheDocument();
    expect(useChatStore.getState().attachments.map((a) => a.cv_id)).toEqual([
      "cv-1",
      "cv-2",
    ]);
  });

  it("never replaces a manually attached chip", async () => {
    const user = userEvent.setup();
    mountWithNav("/");
    await user.click(screen.getByTestId("chat-attach-open"));
    await screen.findByTestId("chat-attach-cv-cv-1");
    await user.click(screen.getByTestId("chat-attach-cv-cv-1"));
    await user.click(screen.getByTestId("nav-cv-2"));
    await screen.findByTestId("chat-attachment-cv-2");
    expect(screen.getByTestId("chat-attachment-cv-1")).toBeInTheDocument();
    const entries = useChatStore.getState().attachments;
    expect(entries.map((a) => a.cv_id)).toEqual(["cv-1", "cv-2"]);
    expect(entries.find((a) => a.cv_id === "cv-1")?.auto).toBeUndefined();
    expect(entries.find((a) => a.cv_id === "cv-2")?.auto).toBe(true);
  });

  it("sends the auto-attached Studio CV with the message", async () => {
    const user = userEvent.setup();
    mount("/cv/cv-1");
    const composer = await screen.findByRole("textbox", { name: "Message" });
    await user.type(composer, "which cv is selected?");
    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(streamChatMessage).toHaveBeenCalledWith(
        "s1",
        "which cv is selected?",
        expect.anything(),
        expect.anything(),
        [{ kind: "cv", cv_id: "cv-1" }],
      ),
    );
  });

  it("keeps the Studio CV detached after removing the chip", async () => {
    const user = userEvent.setup();
    mount("/cv/cv-1");
    await screen.findByTestId("chat-attachment-cv-1");
    await user.click(screen.getByRole("button", { name: "Remove Backend CV" }));
    await waitFor(() =>
      expect(
        screen.queryByTestId("chat-attachment-cv-1"),
      ).not.toBeInTheDocument(),
    );
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByTestId("chat-attachment-cv-1")).not.toBeInTheDocument();
    expect(useChatStore.getState().attachments).toEqual([]);
  });

  it("attaches any CV through the popover and caps at two", async () => {
    const user = userEvent.setup();
    mount("/");
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
    mount("/");
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

  it("keeps the requested reference through the Ask AI session transition", async () => {
    // The reported repro: Ask AI adopts/creates a session DIFFERENT from
    // the active one; the pending attach must survive that transition
    // and ride the first send.
    const user = userEvent.setup();
    const bound = {
      ...SESSION,
      id: "s0",
      context: { surface: "cv_builder", cv_id: 999 },
    };
    const fresh = { ...SESSION, id: "s2", title: "CV chat" };
    useChatStore.setState({
      sessions: [bound],
      activeSessionId: "s0",
      messages: [],
      attachments: [],
      pendingCvAttach: null,
    });
    api.createChatSession.mockResolvedValue(fresh);
    mount("/");
    await openCvChat("cv-1", "docked", "check attached bullets");

    expect(useChatStore.getState().attachments).toEqual([
      { kind: "cv", cv_id: "cv-1", title: "Backend CV" },
    ]);
    const composer = await screen.findByRole("textbox", { name: "Message" });
    await waitFor(() => expect(composer).toHaveValue("check attached bullets"));
    await user.click(composer);
    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(streamChatMessage).toHaveBeenCalledWith(
        "s2",
        "check attached bullets",
        expect.anything(),
        expect.anything(),
        [{ kind: "cv", cv_id: "cv-1" }],
      ),
    );
  });

  it("drops composer references when switching sessions", async () => {
    const user = userEvent.setup();
    mount("/");
    await user.click(screen.getByTestId("chat-attach-open"));
    await screen.findByTestId("chat-attach-cv-cv-1");
    await user.click(screen.getByTestId("chat-attach-cv-cv-1"));
    expect(screen.getByTestId("chat-attachment-cv-1")).toBeInTheDocument();

    await useChatStore.getState().openSession("s-other");
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
    mount("/");
    const chips = await screen.findAllByTestId("cv-ref-chip-cv-1");
    expect(chips.length).toBe(2);
    for (const chip of chips) {
      expect(chip).toHaveTextContent("Backend CV");
      expect(chip).toHaveAttribute("href", "/cv/cv-1");
    }
  });
});
