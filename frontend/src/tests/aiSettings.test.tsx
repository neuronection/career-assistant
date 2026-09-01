import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AIConfig } from "@/pages/settings/AIConfig";
import { useAuthStore } from "@/stores/authStore";
import type { AIModel, AIProvider } from "@/api/ai";

vi.mock("@/api/ai", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/ai")>();
  return {
    ...actual,
    fetchConfigSummary: vi.fn(),
    fetchProviders: vi.fn(),
    fetchAssignments: vi.fn().mockResolvedValue([]),
    fetchModels: vi.fn().mockResolvedValue([]),
    fetchAllModels: vi.fn().mockResolvedValue([]),
    fetchExternalModels: vi.fn().mockResolvedValue([]),
    fetchTasks: vi.fn().mockResolvedValue([
      { value: "match_score", label: "match score" },
      { value: "default", label: "default" },
    ]),
    setAssignment: vi.fn(),
    addModel: vi.fn(),
    deleteModel: vi.fn(),
    testConnection: vi.fn(),
    deleteProvider: vi.fn(),
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

const model: AIModel = {
  id: "m1",
  provider_id: "p1",
  name: "GPT 4o Mini",
  model_name: "gpt-4o-mini",
  is_active: true,
  temperature: null,
  max_tokens: null,
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
    mocked.fetchExternalModels.mockResolvedValue([]);
  });

  it("defaults to the providers tab and lists providers", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId("tab-providers")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("Org OpenAI")).toBeInTheDocument());
    expect(screen.getByText("Global providers")).toBeInTheDocument();
  });

  it("models tab: fetches every provider's models and expands a provider card", async () => {
    renderPage(["/settings/ai?tab=models"]);
    await waitFor(() => expect(screen.getByTestId("models-tab")).toBeInTheDocument());
    await waitFor(() => expect(mocked.fetchModels).toHaveBeenCalledWith("p1"));
    fireEvent.click(screen.getByRole("button", { name: /Org OpenAI/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add model" })).toBeInTheDocument());
  });

  it("models tab: adds a model from the provider catalog", async () => {
    mocked.fetchModels.mockResolvedValue([model]);
    mocked.fetchExternalModels.mockResolvedValue([
      { id: "gpt-4o-mini", name: "GPT 4o mini", owned_by: "openai" },
    ]);
    renderPage(["/settings/ai?tab=models"]);
    fireEvent.click(await screen.findByRole("button", { name: /Org OpenAI/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Add model" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.keyDown(within(dialog).getByRole("combobox", { name: "Model" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("option", { name: /gpt-4o-mini/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Add model" }));
    await waitFor(() =>
      expect(mocked.addModel).toHaveBeenCalledWith("p1", {
        name: "GPT 4o Mini",
        model_name: "gpt-4o-mini",
        temperature: null,
        max_tokens: null,
      }),
    );
  });

  it("models tab: supports manual model ids in the add modal", async () => {
    renderPage(["/settings/ai?tab=models"]);
    fireEvent.click(await screen.findByRole("button", { name: /Org OpenAI/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Add model" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /manual/i }));
    const idInput = within(dialog).getByLabelText("Model");
    fireEvent.change(idInput, { target: { value: "custom-model" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add model" }));
    await waitFor(() =>
      expect(mocked.addModel).toHaveBeenCalledWith(
        "p1",
        expect.objectContaining({ name: "Custom Model", model_name: "custom-model" }),
      ),
    );
  });

  it("models tab: deletes a model through a confirm dialog", async () => {
    mocked.fetchModels.mockResolvedValue([model]);
    renderPage(["/settings/ai?tab=models"]);
    fireEvent.click(await screen.findByRole("button", { name: /Org OpenAI/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Remove gpt-4o-mini" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Delete model gpt-4o-mini\?/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete model" }));
    await waitFor(() => expect(mocked.deleteModel).toHaveBeenCalledWith("m1"));
  });

  it("models tab: system providers are read-only without global rights", async () => {
    useAuthStore.setState({
      token: "t",
      user: { id: "1", email: "a@b.c", full_name: "", is_active: true, is_admin: false },
    });
    mocked.fetchConfigSummary.mockResolvedValue({
      can_manage_global: false,
      mock_allowed: false,
      tasks: [],
    });
    mocked.fetchModels.mockResolvedValue([model]);
    renderPage(["/settings/ai?tab=models"]);
    fireEvent.click(await screen.findByRole("button", { name: /Org OpenAI/ }));
    await waitFor(() => expect(screen.getByText("gpt-4o-mini")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Add model" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit gpt-4o-mini" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove gpt-4o-mini" })).not.toBeInTheDocument();
  });

  it("providers tab: tests a connection through the first active model", async () => {
    mocked.fetchAllModels.mockResolvedValue([
      { ...model, provider_name: "Org OpenAI", provider_scope: "system", provider_type: "openai" },
    ]);
    mocked.testConnection.mockResolvedValue({ ok: true, reply: "OK" });
    renderPage();
    await waitFor(() => expect(screen.getByText("Org OpenAI")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("1 models")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Test" }));
    await waitFor(() => expect(mocked.testConnection).toHaveBeenCalledWith("p1", "m1"));
    expect(await screen.findByText("Connected")).toBeInTheDocument();
  });

  it("providers tab: connection test is unavailable without a registered model", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Org OpenAI")).toBeInTheDocument());
    expect(screen.getByText(/Register a model first/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Test" })).not.toBeInTheDocument();
  });

  it("providers tab: deletes a provider through a confirm dialog", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Delete Org OpenAI" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Delete Org OpenAI?")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mocked.deleteProvider).toHaveBeenCalledWith("p1"));
  });

  it("tasks tab: renders the fallback section and per-task assignment rows", async () => {
    mocked.fetchTasks.mockResolvedValue([
      { value: "match_score", label: "match score" },
      { value: "default", label: "default (all tasks)" },
    ]);
    mocked.fetchAllModels.mockResolvedValue([
      { ...model, provider_name: "Org OpenAI", provider_scope: "system", provider_type: "openai" },
    ]);
    mocked.fetchAssignments.mockResolvedValue([
      { id: "a1", task_type: "default", scope: "system", model_id: "m1", is_active: true },
    ]);
    renderPage(["/settings/ai?tab=tasks"]);
    await waitFor(() => expect(screen.getByText("Fallback model")).toBeInTheDocument());
    expect(screen.getByText("All tasks")).toBeInTheDocument();
    expect(screen.getByText("Fallback")).toBeInTheDocument();
    expect(await screen.findByRole("combobox", { name: "Fallback — All tasks" })).toHaveTextContent(
      "GPT 4o Mini"
    );
    expect(screen.getByText("Job Match Scoring")).toBeInTheDocument();
    expect(screen.getByText(/Unassigned — falls back/)).toBeInTheDocument();
    expect(mocked.fetchAllModels).toHaveBeenCalled();
  });

  it("tasks tab: assigns a model to a task from its picker", async () => {
    mocked.fetchTasks.mockResolvedValue([
      { value: "match_score", label: "match score" },
      { value: "default", label: "default (all tasks)" },
    ]);
    mocked.fetchAllModels.mockResolvedValue([
      { ...model, provider_name: "Org OpenAI", provider_scope: "system", provider_type: "openai" },
    ]);
    mocked.setAssignment.mockResolvedValue({
      id: "a2",
      task_type: "match_score",
      scope: "system",
      model_id: "m1",
      is_active: true,
    });
    renderPage(["/settings/ai?tab=tasks"]);
    const picker = await screen.findByRole("combobox", { name: "Job Match Scoring" });
    fireEvent.keyDown(picker, { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("option", { name: /GPT 4o Mini/ }));
    await waitFor(() =>
      expect(mocked.setAssignment).toHaveBeenCalledWith("match_score", {
        scope: "system",
        model_id: "m1",
      }),
    );
  });

  it("tasks tab: clears an assignment with the row button", async () => {
    mocked.fetchTasks.mockResolvedValue([
      { value: "match_score", label: "match score" },
      { value: "default", label: "default (all tasks)" },
    ]);
    mocked.fetchAllModels.mockResolvedValue([
      { ...model, provider_name: "Org OpenAI", provider_scope: "system", provider_type: "openai" },
    ]);
    mocked.fetchAssignments.mockResolvedValue([
      { id: "a2", task_type: "match_score", scope: "system", model_id: "m1", is_active: true },
    ]);
    renderPage(["/settings/ai?tab=tasks"]);
    fireEvent.click(await screen.findByRole("button", { name: "Clear assignment — Job Match Scoring" }));
    await waitFor(() =>
      expect(mocked.setAssignment).toHaveBeenCalledWith("match_score", {
        scope: "system",
        model_id: null,
      }),
    );
  });
});
