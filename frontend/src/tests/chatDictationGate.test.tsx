import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";

import type { ChatStreamCallbacks } from "@/api/chatStream";
import { ChatDock } from "@/features/chat/components/chat/ChatWidget";
import { resetConfigSummaryCache } from "@/hooks/useConfigSummary";
import { useChatStore } from "@/stores/chatStore";
import { useAuthStore } from "@/stores/authStore";
import type { ConfigSummary, EffectiveAssignment } from "@/api/ai";

const aiApi = vi.hoisted(() => ({
  fetchAiTools: vi.fn(),
  fetchConfigSummary: vi.fn(),
  transcribeAudio: vi.fn(),
  classifyDictationError: vi.fn(),
}));

vi.mock("@/api/ai", () => ({
  fetchAiTools: aiApi.fetchAiTools,
  fetchConfigSummary: aiApi.fetchConfigSummary,
  transcribeAudio: aiApi.transcribeAudio,
  classifyDictationError: aiApi.classifyDictationError,
}));

vi.mock("@/api/chatStream", () => ({
  streamChatMessage: (
    _id: string,
    _content: string,
    _callbacks: ChatStreamCallbacks,
    _signal?: AbortSignal,
  ) => new Promise<void>(() => {}),
  streamChatEdit: vi.fn(),
  streamChatRegenerate: vi.fn(),
}));

vi.mock("@/api/universities", () => ({
  fetchChatSessions: vi.fn().mockResolvedValue([]),
  fetchMessages: vi.fn().mockResolvedValue([]),
  createChatSession: vi.fn(),
  renameChatSession: vi.fn(),
  deleteChatSession: vi.fn(),
}));

const SESSION = {
  id: "s1",
  title: "Session",
  context: null,
  created_at: "2026-11-12T10:00:00Z",
  last_activity_at: "2026-11-12T10:00:00Z",
};

function assignment(source: string): EffectiveAssignment {
  return {
    task_type: "transcribe",
    source,
    provider_type: source === "unconfigured" ? "none" : "openai",
    model_name: source === "unconfigured" ? "not configured" : "whisper-1",
    api_base: "",
  };
}

function summary(tasks: EffectiveAssignment[]): ConfigSummary {
  return { tasks, can_manage_global: false, mock_allowed: false };
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
}

function mount() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <LocationProbe />
      <ChatDock />
    </MemoryRouter>,
  );
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

describe("composer dictation capability gate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useAuthStore.setState({ user: null });
    resetConfigSummaryCache();
    useChatStore.setState({
      sessions: [SESSION],
      activeSessionId: "s1",
      messages: [],
      attachments: [],
      pendingCvAttach: null,
      chatMode: "docked",
    });
    aiApi.fetchAiTools.mockResolvedValue([]);
  });

  it("keeps the mic when the transcribe task is configured", async () => {
    aiApi.fetchConfigSummary.mockResolvedValue(summary([assignment("user")]));
    mount();
    await flush();

    expect(aiApi.fetchConfigSummary).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("button", { name: "Dictate" })).toBeInTheDocument();
    expect(screen.queryByText("Dictation unavailable")).not.toBeInTheDocument();
  });

  it("keeps the mic when the summary has no transcribe row", async () => {
    aiApi.fetchConfigSummary.mockResolvedValue(
      summary([
        {
          task_type: "match_score",
          source: "unconfigured",
          provider_type: "none",
          model_name: "not configured",
          api_base: "",
        },
      ]),
    );
    mount();
    await flush();

    expect(screen.getByRole("button", { name: "Dictate" })).toBeInTheDocument();
    expect(screen.queryByText("Dictation unavailable")).not.toBeInTheDocument();
  });

  it("replaces the mic when the transcribe task is unconfigured", async () => {
    aiApi.fetchConfigSummary.mockResolvedValue(
      summary([assignment("unconfigured")]),
    );
    mount();

    expect(await screen.findByText("Dictation unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("No speech-to-text model is assigned."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dictate" })).not.toBeInTheDocument();
  });

  it("renders the unavailable notice above the input row, not in a toolbar slot", async () => {
    aiApi.fetchConfigSummary.mockResolvedValue(
      summary([assignment("unconfigured")]),
    );
    mount();
    const notice = await screen.findByRole("note");
    expect(notice.closest('[data-as="chat-composer-row"]')).toBeNull();
    expect(notice.closest('[data-as="chat-composer"]')).not.toBeNull();
  });

  it("dismisses the notice per user and keeps the mic absent", async () => {
    useAuthStore.setState({
      user: { id: "user-a", email: "a@b.c", full_name: "A", is_active: true, is_admin: false },
    });
    aiApi.fetchConfigSummary.mockResolvedValue(
      summary([assignment("unconfigured")]),
    );
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: "Dismiss" }));

    expect(screen.queryByText("Dictation unavailable")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dictate" })).not.toBeInTheDocument();
    expect(localStorage.getItem("ca:chat:dictation-dismissed:user-a")).toBe("1");
  });

  it("keeps dismissals isolated between users", async () => {
    useAuthStore.setState({
      user: { id: "user-a", email: "a@b.c", full_name: "A", is_active: true, is_admin: false },
    });
    aiApi.fetchConfigSummary.mockResolvedValue(
      summary([assignment("unconfigured")]),
    );
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: "Dismiss" }));
    expect(localStorage.getItem("ca:chat:dictation-dismissed:user-a")).toBe("1");

    act(() => {
      useAuthStore.setState({
        user: { id: "user-b", email: "b@b.c", full_name: "B", is_active: true, is_admin: false },
      });
    });
    expect(await screen.findByRole("note")).toBeInTheDocument();
    expect(localStorage.getItem("ca:chat:dictation-dismissed:user-b")).toBeNull();
  });

  it("does not persist a dismissal before the user resolves", async () => {
    useAuthStore.setState({ user: null });
    aiApi.fetchConfigSummary.mockResolvedValue(
      summary([assignment("unconfigured")]),
    );
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: "Dismiss" }));
    expect(
      Object.keys(localStorage).some((key) =>
        key.startsWith("ca:chat:dictation-dismissed")
      )
    ).toBe(false);
  });

  it("clears a stored dismissal once the transcribe task is configured", async () => {
    useAuthStore.setState({
      user: { id: "user-a", email: "a@b.c", full_name: "A", is_active: true, is_admin: false },
    });
    localStorage.setItem("ca:chat:dictation-dismissed:user-a", "1");
    aiApi.fetchConfigSummary.mockResolvedValue(summary([assignment("user")]));
    mount();
    await flush();

    await waitFor(() => {
      expect(localStorage.getItem("ca:chat:dictation-dismissed:user-a")).toBeNull();
    });
    expect(screen.getByRole("button", { name: "Dictate" })).toBeInTheDocument();
  });

  it("swaps back to the mic after a settings reset reports a configured task", async () => {
    aiApi.fetchConfigSummary.mockResolvedValueOnce(
      summary([assignment("unconfigured")]),
    );
    mount();
    expect(await screen.findByText("Dictation unavailable")).toBeInTheDocument();

    aiApi.fetchConfigSummary.mockResolvedValueOnce(summary([assignment("user")]));
    await act(async () => {
      resetConfigSummaryCache();
    });

    await waitFor(() => {
      expect(screen.queryByText("Dictation unavailable")).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Dictate" })).toBeInTheDocument();
    expect(aiApi.fetchConfigSummary).toHaveBeenCalledTimes(2);
  });

  it("keeps the mic while the config summary is loading", async () => {
    aiApi.fetchConfigSummary.mockReturnValue(new Promise<ConfigSummary>(() => {}));
    mount();
    await flush();

    expect(screen.getByRole("button", { name: "Dictate" })).toBeInTheDocument();
    expect(screen.queryByText("Dictation unavailable")).not.toBeInTheDocument();
  });

  it("keeps the mic when the config summary request fails", async () => {
    aiApi.fetchConfigSummary.mockRejectedValue(new Error("summary failed"));
    mount();
    await flush();

    expect(screen.getByRole("button", { name: "Dictate" })).toBeInTheDocument();
    expect(screen.queryByText("Dictation unavailable")).not.toBeInTheDocument();
  });

  it("deep-links the unavailable action to the AI task settings", async () => {
    aiApi.fetchConfigSummary.mockResolvedValue(
      summary([assignment("unconfigured")]),
    );
    const user = userEvent.setup();
    mount();

    await user.click(
      await screen.findByRole("button", { name: "Open AI settings" }),
    );

    await waitFor(() => {
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/settings/ai?tab=tasks",
      );
    });
  });

  it("reads one shared summary across mounts inside the stale window", async () => {
    aiApi.fetchConfigSummary.mockResolvedValue(summary([assignment("user")]));
    const first = mount();
    await flush();
    first.unmount();

    mount();
    await flush();

    expect(aiApi.fetchConfigSummary).toHaveBeenCalledTimes(1);
  });
});
