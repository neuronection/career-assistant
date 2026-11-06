import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { OnboardingSetup } from "@/pages/OnboardingSetup";
import { useAuthStore } from "@/stores/authStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import type { AIProvider, ProviderSetupResult } from "@/api/ai";
import type { AiStatus, Bootstrap } from "@/types/wire";

vi.mock("@/api/ai", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/ai")>();
  return {
    ...mod,
    fetchProviderPresets: vi.fn(),
    fetchProviders: vi.fn(),
    fetchConfigSummary: vi.fn(),
    fetchModels: vi.fn(),
    fetchTasks: vi.fn(),
    fetchAllModels: vi.fn(),
    fetchAssignments: vi.fn(),
    setAssignment: vi.fn(),
    setupProviderPreset: vi.fn(),
    testConnection: vi.fn(),
    createProvider: vi.fn(),
    updateProvider: vi.fn(),
  };
});

vi.mock("@/api/stages", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/stages")>();
  return {
    ...mod,
    fetchBootstrap: vi.fn(),
    setAiSetupDismissed: vi.fn(),
  };
});

const aiApi = vi.mocked(await import("@/api/ai"));
const stagesApi = vi.mocked(await import("@/api/stages"));

function aiStatus(overrides: Partial<AiStatus> = {}): AiStatus {
  return {
    configured: false,
    provider_type: null,
    default_model: null,
    task_coverage: { assigned: 0, total: 4, missing: ["text", "vision", "stt", "embeddings"] },
    mock_active: false,
    setup_dismissed: false,
    ...overrides,
  };
}

function bootstrap(ai: AiStatus): Bootstrap {
  const weights = { skills: 3, location: 3, experience: 3, education: 3, interests: 3, values: 3 };
  return {
    career_stage: "student",
    stage_source: "derived",
    onboarding_path: null,
    features: { universities: true, grade_fields: true, education_step: true },
    suggested_scoring_weights: weights,
    effective_scoring_weights: weights,
    weights_overridden: false,
    fit_stale: false,
    target_mode: false,
    ai,
  };
}

const provider: AIProvider = {
  id: "p-new",
  name: "OpenAI",
  scope: "user",
  user_id: "u1",
  provider_type: "openai",
  api_base: "https://api.openai.com/v1",
  api_key: "***",
  is_active: true,
  is_local: false,
  country: null,
  preset_key: "openai",
  is_mine: true,
  created_at: "2026-10-21T00:00:00Z",
};

function setupResult(overrides: Partial<ProviderSetupResult> = {}): ProviderSetupResult {
  return {
    ok: true,
    provider,
    catalog_count: 1,
    curated_missed: false,
    assigned_chat_model: null,
    assigned_vision_model: null,
    assigned_stt_model: null,
    assigned_decision_slots: null,
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/onboarding/setup"]}>
      <Routes>
        <Route path="/onboarding/setup" element={<OnboardingSetup />} />
        <Route path="/onboarding" element={<div>onboarding-hero</div>} />
        <Route path="/settings/ai" element={<div>ai-settings</div>} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useBootstrapStore.getState().reset();
  useAuthStore.setState({
    user: {
      id: "u1",
      email: "student@example.com",
      full_name: "Student",
      is_admin: true,
      is_active: true,
    },
  });
  aiApi.fetchProviderPresets.mockResolvedValue({
    openai: {
      name: "OpenAI",
      type: "openai",
      base_url: "https://api.openai.com/v1",
      fixed_base: true,
      local: false,
      curated_models: ["gpt-test"],
      preferred_model: { id: "gpt-test", name: "gpt-test", caps: ["text", "vision"] },
    },
  });
  aiApi.fetchProviders.mockResolvedValue([]);
  aiApi.fetchConfigSummary.mockResolvedValue({
    can_manage_global: true,
    mock_allowed: true,
    tasks: [],
  } as unknown as Awaited<ReturnType<typeof aiApi.fetchConfigSummary>>);
  aiApi.fetchModels.mockResolvedValue([
    {
      id: "m1",
      provider_id: provider.id,
      name: "gpt-test",
      model_name: "gpt-test",
    } as Awaited<ReturnType<typeof aiApi.fetchModels>>[number],
  ]);
  aiApi.fetchTasks.mockResolvedValue([
    { value: "text", label: "default (text models)", is_slot: true },
    { value: "chat", label: "chat", requires: "text" },
  ]);
  aiApi.fetchAllModels.mockResolvedValue([
    {
      id: "m1",
      provider_id: provider.id,
      provider_name: "OpenAI",
      provider_scope: "user",
      provider_type: "openai",
      name: "gpt-test",
      model_name: "gpt-test",
    } as Awaited<ReturnType<typeof aiApi.fetchAllModels>>[number],
  ]);
  aiApi.fetchAssignments.mockResolvedValue([]);
  aiApi.testConnection.mockResolvedValue({ ok: true, reply: "OK" });
  stagesApi.fetchBootstrap.mockResolvedValue(bootstrap(aiStatus()));
  stagesApi.setAiSetupDismissed.mockResolvedValue(
    bootstrap(aiStatus({ setup_dismissed: true }))
  );
});

describe("OnboardingSetup", () => {
  it("offers the provider tiles and skips with a persisted dismissal", async () => {
    renderPage();
    expect(await screen.findByTestId("ai-setup-page")).toBeInTheDocument();
    expect(await screen.findByText("OpenAI")).toBeInTheDocument();
    expect(screen.getByText("Set up manually")).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("ai-setup-skip"));
    await waitFor(() => expect(stagesApi.setAiSetupDismissed).toHaveBeenCalledWith(true));
    expect(await screen.findByText("onboarding-hero")).toBeInTheDocument();
  });

  it("walks tiles → review → connection test → assignments", async () => {
    aiApi.setupProviderPreset
      .mockResolvedValueOnce(setupResult())
      .mockResolvedValueOnce(setupResult({ assigned_chat_model: "gpt-test" }));
    stagesApi.fetchBootstrap
      .mockResolvedValueOnce(bootstrap(aiStatus()))
      .mockResolvedValue(bootstrap(aiStatus({ configured: true, provider_type: "openai" })));

    renderPage();
    await userEvent.click(await screen.findByText("OpenAI"));
    expect(await screen.findByText("Set up OpenAI")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("API key"), "sk-test-key");

    await userEvent.click(screen.getByRole("button", { name: /Set up automatically/i }));
    await waitFor(() => expect(aiApi.setupProviderPreset).toHaveBeenCalledTimes(1));

    await userEvent.click(await screen.findByRole("button", { name: /Apply setup/i }));
    await waitFor(() => expect(aiApi.setupProviderPreset).toHaveBeenCalledTimes(2));

    expect(await screen.findByTestId("ai-setup-verify")).toBeInTheDocument();
    await waitFor(() => expect(aiApi.testConnection).toHaveBeenCalledWith("p-new", "m1"));
    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(await screen.findByTestId("tasks-tab")).toBeInTheDocument();
    await waitFor(() => expect(stagesApi.fetchBootstrap).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByTestId("ai-setup-finish")).toBeEnabled());
  });

  it("renders typed copy when the connection test fails", async () => {
    aiApi.setupProviderPreset.mockResolvedValue(setupResult());
    aiApi.testConnection.mockResolvedValue({
      ok: false,
      code: "invalid_key",
      error: "Error code: 401 - bad key",
    });
    renderPage();
    await userEvent.click(await screen.findByText("OpenAI"));
    await userEvent.type(await screen.findByLabelText("API key"), "sk-test-key");
    await userEvent.click(
      await screen.findByRole("button", { name: /Set up automatically/i })
    );
    await userEvent.click(await screen.findByRole("button", { name: /Apply setup/i }));

    expect(
      await screen.findByText(/That API key was rejected by the provider/i)
    ).toBeInTheDocument();
  });

  it("shows the ready state once a provider is configured", async () => {
    stagesApi.fetchBootstrap.mockResolvedValue(
      bootstrap(
        aiStatus({
          configured: true,
          provider_type: "openai",
          default_model: "gpt-test",
          task_coverage: { assigned: 2, total: 4, missing: ["stt", "embeddings"] },
        })
      )
    );
    useBootstrapStore
      .getState()
      .apply(
        bootstrap(
          aiStatus({
            configured: true,
            provider_type: "openai",
            default_model: "gpt-test",
            task_coverage: { assigned: 2, total: 4, missing: ["stt", "embeddings"] },
          })
        )
      );
    renderPage();
    expect(await screen.findByTestId("ai-setup-ready")).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("ai-setup-continue"));
    expect(await screen.findByText("onboarding-hero")).toBeInTheDocument();
  });
});
