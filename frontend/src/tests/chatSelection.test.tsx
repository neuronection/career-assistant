import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { ChatWidget } from "@/components/chat/ChatWidget";
import { useChatStore } from "@/stores/chatStore";
import type { ChatStreamCallbacks } from "@/api/chatStream";
import { copyText } from "@/lib/clipboard";

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

vi.mock("@/api/ai", () => ({
  fetchAiTools: vi.fn().mockResolvedValue([]),
  transcribeAudio: vi.fn(),
  classifyDictationError: vi.fn(),
}));

vi.mock("@/lib/clipboard", () => ({
  copyText: vi.fn().mockResolvedValue(true),
}));

const SELECTION = "the nursing track suits you";

beforeAll(() => {
  const selection = window.getSelection();
  if (selection !== null) {
    const proto = Object.getPrototypeOf(selection) as {
      toString: () => string;
    };
    let text = "";
    proto.toString = () => text;
    (window as unknown as { __stubSelection: (value: string) => void })
      .__stubSelection = (value: string) => {
      text = value;
    };
  }
});

function selectElement(element: HTMLElement, text: string) {
  const range = document.createRange();
  range.selectNodeContents(element);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  (window as unknown as { __stubSelection: (value: string) => void })
    .__stubSelection(text);
}

function renderWidget() {
  return render(
    <MemoryRouter>
      <ChatWidget />
    </MemoryRouter>,
  );
}

async function openBubbleWithMessage() {
  useChatStore.setState({
    chatMode: "bubble",
    bubbleOpen: false,
    activeSessionId: "s1",
    sessions: [],
    messages: [
      {
        id: "m1",
        role: "user",
        content: "what fits me?",
        metadata_json: null,
        created_at: "2026-09-19T09:00:00Z",
      },
      {
        id: "m2",
        role: "assistant",
        content: `${SELECTION}`,
        metadata_json: null,
        created_at: "2026-09-19T09:00:05Z",
      },
    ],
  });
  api.fetchChatSessions.mockResolvedValue([]);
  renderWidget();
  await userEvent.click(
    screen.getByRole("button", { name: "Open chat assistant" }),
  );
  await waitFor(() =>
    expect(screen.getByText(SELECTION)).toBeInTheDocument(),
  );
  return screen.getByText(SELECTION);
}

describe("chat selection context menu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.getSelection()?.removeAllRanges();
  });

  it("opens a menu on right-click over a selection and copies it", async () => {
    const message = await openBubbleWithMessage();
    selectElement(message, SELECTION);

    message.dispatchEvent(
      new MouseEvent("contextmenu", {
        bubbles: true,
        cancelable: true,
        clientX: 40,
        clientY: 40,
      }),
    );

    const menu = await screen.findByRole("menu");
    expect(menu).toBeInTheDocument();
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Copy" }));
    await waitFor(() => expect(copyText).toHaveBeenCalledWith(SELECTION));
  });

  it("quotes the selection into the composer", async () => {
    const message = await openBubbleWithMessage();
    selectElement(message, SELECTION);

    message.dispatchEvent(
      new MouseEvent("contextmenu", {
        bubbles: true,
        cancelable: true,
        clientX: 40,
        clientY: 40,
      }),
    );
    const menu = await screen.findByRole("menu");
    await userEvent.click(
      within(menu).getByRole("menuitem", { name: "Quote in chat" }),
    );

    const composer = document.querySelector<HTMLTextAreaElement>(
      '[data-as="chat-composer"] textarea',
    );
    await waitFor(() =>
      expect(composer?.value).toBe(`> ${SELECTION}\n\n`),
    );
  });

  it("stays closed without a selection or for outside selections", async () => {
    const message = await openBubbleWithMessage();

    message.dispatchEvent(
      new MouseEvent("contextmenu", {
        bubbles: true,
        cancelable: true,
        clientX: 40,
        clientY: 40,
      }),
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    const header = screen.getByText("Career Assistant", { selector: "div" });
    selectElement(header, "Career Assistant");
    header.dispatchEvent(
      new MouseEvent("contextmenu", {
        bubbles: true,
        cancelable: true,
        clientX: 40,
        clientY: 40,
      }),
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
