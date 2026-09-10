import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ChatDock, ChatWidget } from "@/components/chat/ChatWidget";
import { openCvChat, cvAskKey } from "@/components/chat/cvChatLink";
import { useChatStore } from "@/stores/chatStore";
import { useCvBuilderLink } from "@/stores/cvBuilderLinkStore";
import type { CvAssistantState } from "@/types/cvAssistant";

const createChatSession = vi.fn();
const fetchMessages = vi.fn();
const fetchChatSessions = vi.fn();

vi.mock("@/api/universities", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/universities")>();
  return {
    ...mod,
    createChatSession: (...args: unknown[]) => createChatSession(...args),
    fetchMessages: (...args: unknown[]) => fetchMessages(...args),
    fetchChatSessions: (...args: unknown[]) => fetchChatSessions(...args),
  };
});

const state: CvAssistantState = {
  document: {
    id: "cv-1",
    title: "Backend Intern CV",
    kind: "resume",
    language: "en",
    page_size: "a4",
    max_pages: 1,
    status: "draft",
    template_id: "tpl-2",
    photo_document_id: null,
  },
  blocks: [{ kind: "header" }],
  overrides: {},
  html: "<html><body>updated</body></html>",
  metrics: { estimated_pages: 1 },
  resolution: { snapshot_index: { experience: ["exp-1"] } },
  operations: [{ op: "set_template", ok: true, detail: "template “Modern”" }],
  critique: null,
  version: 4,
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  useChatStore.setState({
    sessions: [],
    activeSessionId: null,
    messages: [],
    pinnedAsks: {},
    chatMode: "bubble",
  });
  useCvBuilderLink.setState({ lastBuilderState: null, flushCallback: null });
  createChatSession.mockResolvedValue({ id: "s-1", title: "CV assistant" });
  fetchMessages.mockResolvedValue([]);
  fetchChatSessions.mockResolvedValue([]);
});

afterEach(() => {
  localStorage.clear();
  useChatStore.setState({
    sessions: [],
    activeSessionId: null,
    messages: [],
    pinnedAsks: {},
    chatMode: "bubble",
  });
  useCvBuilderLink.setState({ lastBuilderState: null, flushCallback: null });
});

describe("openCvChat (the one chatbot, bound to a CV)", () => {
  it("creates a CV-bound session, pins it and docks by default", async () => {
    await openCvChat("cv-1");
    expect(createChatSession).toHaveBeenCalledWith({
      title: "CV assistant",
      context: { surface: "cv_builder", cv_id: "cv-1" },
    });
    expect(useChatStore.getState().pinnedAsks[cvAskKey("cv-1")]).toBe("s-1");
    expect(useChatStore.getState().activeSessionId).toBe("s-1");
    expect(useChatStore.getState().chatMode).toBe("docked");
  });

  it("adopts the pinned session on later calls", async () => {
    await openCvChat("cv-1");
    await openCvChat("cv-1", "bubble");
    expect(createChatSession).toHaveBeenCalledTimes(1);
    expect(useChatStore.getState().activeSessionId).toBe("s-1");
    expect(useChatStore.getState().chatMode).toBe("bubble");
  });
});

describe("ChatWidget view switcher (bubble ↔ docked ↔ page)", () => {
  it("renders the popup launcher with view buttons; docked hides it", () => {
    render(
      <MemoryRouter>
        <ChatWidget />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("chat-widget")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /open chat assistant/i }));
    expect(screen.getByTestId("chat-view-docked")).toBeInTheDocument();
    expect(screen.getByTestId("chat-view-page")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("chat-view-docked"));
    expect(useChatStore.getState().chatMode).toBe("docked");
    expect(screen.queryByTestId("chat-widget")).toBeNull();
  });

  it("the docked column mounts the same chat surface with a switcher back to popup", () => {
    useChatStore.setState({ chatMode: "docked" });
    useChatStore.setState({
      activeSessionId: "s-1",
      sessions: [
        {
          id: "s-1",
          title: "CV assistant",
          context: { surface: "cv_builder", cv_id: "cv-1" },
          created_at: "2026-09-07T00:00:00Z",
        },
      ],
    });
    render(
      <MemoryRouter>
        <ChatWidget />
      </MemoryRouter>,
    );
    expect(screen.queryByTestId("chat-widget")).toBeNull();
  });
});

describe("ChatDock (the docked shape of the one chatbot)", () => {
  it("renders the shared surface with the view switcher in a CV-bound session", () => {
    useChatStore.setState({
      activeSessionId: "s-1",
      messages: [],
      sessions: [
        {
          id: "s-1",
          title: "CV assistant",
          context: { surface: "cv_builder", cv_id: "cv-1" },
          created_at: "2026-09-07T00:00:00Z",
        },
      ],
    });
    render(
      <MemoryRouter>
        <ChatDock />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("chat-dock")).toBeInTheDocument();
    expect(screen.getByTestId("chat-dock-resize-handle")).toBeInTheDocument();
    expect(screen.getByTestId("chat-view-popup")).toBeInTheDocument();
    expect(screen.getByTestId("chat-view-page")).toBeInTheDocument();
    // CV-bound: prompt chips instead of the generic suggestions
    expect(screen.getAllByTestId("cv-chat-prompt").length).toBeGreaterThan(0);
  });
});

describe("CV-bound empty state + builder link", () => {
  it("shows CV prompt suggestions when the active session is CV-bound", () => {
    useChatStore.setState({
      activeSessionId: "s-1",
      messages: [],
      sessions: [
        {
          id: "s-1",
          title: "CV assistant",
          context: { surface: "cv_builder", cv_id: "cv-1" },
          created_at: "2026-09-07T00:00:00Z",
        },
      ],
    });
    render(
      <MemoryRouter>
        <ChatWidget />
      </MemoryRouter>,
    );
    // bubble mode: open the launcher panel to see the transcript
    fireEvent.click(screen.getByRole("button", { name: /open chat assistant/i }));
    expect(screen.getAllByTestId("cv-chat-prompt").length).toBeGreaterThan(0);
    expect(screen.queryAllByTestId("chat-suggestion")).toHaveLength(0);
  });

  it("applies builder_state through the link store", () => {
    const seen: CvAssistantState[] = [];
    useCvBuilderLink.subscribe((s) => seen.push(s.lastBuilderState as CvAssistantState));
    useCvBuilderLink.getState().applyBuilderState(state);
    expect(seen[seen.length - 1]?.document.template_id).toBe("tpl-2");
    expect(useCvBuilderLink.getState().lastBuilderState?.version).toBe(4);
  });
});
