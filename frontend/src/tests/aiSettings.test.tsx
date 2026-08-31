import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AIConfig } from "@/pages/settings/AIConfig";
import { useAuthStore } from "@/stores/authStore";
import type { AIProvider } from "@/api/ai";

vi.mock("@/api/ai", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/ai")>();
  return {
    ...actual,
    fetchConfigSummary: vi.fn(),
    fetchProviders: vi.fn(),
    fetchAssignments: vi.fn().mockResolvedValue([]),
    fetchModels: vi.fn().mockResolvedValue([]),
    fetchAllModels: vi.fn().mockResolvedValue([]),
    fetchTasks: vi.fn().mockResolvedValue([
      { value: "match_score", label: "match score" },
      { value: "default", label: "default" },
    ]),
    setAssignment: vi.fn(),
  };
});

const mocked = vi.mocked(await import("@/api/ai"));

const provider: AIProvider = {
  id: "p1",
  name: "Org OpenAI",
  scope: "system",
  user_id: null,
  provider_type: "openai",
  api_base: "https://api.openai.com/v1",
  api_key: "***",
  is_active: true,
  is_mine: true,
  created_at: "2026-01-01T00:00:00Z",
};

function renderPage(initialEntries = ["/settings/ai"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <AIConfig />
    </MemoryRouter>
  );
}

describe("AIConfig (settings > AI)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({
      token: "t",
      user: { id: "1", email: "a@b.c", full_name: "", is_active: true, is_admin: true },
    });
    mocked.fetchConfigSummary.mockResolvedValue({
      can_manage_global: true,
      mock_allowed: true,
      tasks: [
        {
          task_type: "match_score",
          source: "system:match_score",
          provider_type: "openai",
          model_name: "gpt-4o-mini",
          api_base: "https://api.openai.com/v1",
        },
      ],
    });
    mocked.fetchProviders.mockResolvedValue([provider]);
    mocked.fetchAssignments.mockResolvedValue([]);
    mocked.fetchModels.mockResolvedValue([]);
    mocked.fetchAllModels.mockResolvedValue([]);
  });

  it("defaults to the providers tab and lists providers", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId("tab-providers")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("Org OpenAI")).toBeInTheDocument());
    expect(screen.getByText("Global providers")).toBeInTheDocument();
  });

  it("models tab: provider cards expand and lazily load their models", async () => {
    renderPage(["/settings/ai?tab=models"]);
    await waitFor(() => expect(screen.getByTestId("models-tab")).toBeInTheDocument());
    expect(screen.getByText("Models per Provider")).toBeInTheDocument();
    expect(mocked.fetchModels).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Org OpenAI"));
    await waitFor(() => expect(mocked.fetchModels).toHaveBeenCalledWith("p1"));
    expect(screen.getByText("Models for Org OpenAI")).toBeInTheDocument();
    expect(screen.getByText("Add Model")).toBeInTheDocument();
  });

  it("tasks tab renders assignment cards with fallback note", async () => {
    renderPage(["/settings/ai?tab=tasks"]);
    await waitFor(() => expect(screen.getByTestId("tasks-tab")).toBeInTheDocument());
    expect(screen.getByText("Task Assignments")).toBeInTheDocument();
    expect(screen.getByText("Global Default Fallback")).toBeInTheDocument();
    expect(screen.getByText("Job Match Scoring")).toBeInTheDocument();
    expect(screen.getAllByText(/Not assigned/i).length).toBeGreaterThan(0);
    expect(mocked.fetchAllModels).toHaveBeenCalled();
  });
});
