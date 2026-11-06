import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { AiMockChip, AiSetupPrompt, AI_SETUP_ROUTE } from "@/components/ai/AiSetupPrompt";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import type { AiStatus, Bootstrap } from "@/types/wire";

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

function bootstrapWith(ai: AiStatus | undefined): Bootstrap {
  return {
    career_stage: "student",
    stage_source: "derived",
    features: { universities: true, grade_fields: true, education_step: true },
    suggested_scoring_weights: {
      skills: 3,
      location: 3,
      experience: 3,
      education: 3,
      interests: 3,
      values: 3,
    },
    effective_scoring_weights: {
      skills: 3,
      location: 3,
      experience: 3,
      education: 3,
      interests: 3,
      values: 3,
    },
    weights_overridden: false,
    fit_stale: false,
    target_mode: false,
    ai,
  };
}

function renderPrompt(variant: "banner" | "card" | "inline") {
  return render(
    <MemoryRouter>
      <AiSetupPrompt variant={variant} />
    </MemoryRouter>
  );
}

beforeEach(() => {
  useBootstrapStore.getState().reset();
});

describe("AiSetupPrompt", () => {
  it.each(["banner", "card", "inline"] as const)(
    "renders the %s variant while AI is unconfigured",
    (variant) => {
      useBootstrapStore.getState().apply(bootstrapWith(aiStatus()));
      renderPrompt(variant);
      const prompt = screen.getByTestId(`ai-setup-prompt-${variant}`);
      expect(prompt).toBeInTheDocument();
      expect(screen.getByTestId("ai-setup-open")).toHaveAttribute(
        "href",
        AI_SETUP_ROUTE
      );
    }
  );

  it("offers the setup route the first-run wizard lives on", () => {
    expect(AI_SETUP_ROUTE).toBe("/onboarding/setup");
  });

  it("disappears once a provider is configured", () => {
    useBootstrapStore
      .getState()
      .apply(bootstrapWith(aiStatus({ configured: true, provider_type: "openai" })));
    renderPrompt("card");
    expect(screen.queryByTestId("ai-setup-prompt-card")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ai-setup-open")).not.toBeInTheDocument();
  });

  it("stays hidden until the bootstrap payload lands", () => {
    renderPrompt("banner");
    expect(screen.queryByTestId("ai-setup-prompt-banner")).not.toBeInTheDocument();
  });

  it("keeps prompting after a dismissed setup (the gap is still there)", () => {
    useBootstrapStore
      .getState()
      .apply(bootstrapWith(aiStatus({ setup_dismissed: true })));
    renderPrompt("banner");
    expect(screen.getByTestId("ai-setup-prompt-banner")).toBeInTheDocument();
  });
});

describe("AiMockChip", () => {
  it("marks a mock provider as dev-only whenever it is serving", () => {
    useBootstrapStore
      .getState()
      .apply(bootstrapWith(aiStatus({ configured: true, mock_active: true })));
    render(<AiMockChip />);
    expect(screen.getByTestId("ai-mock-chip")).toHaveTextContent(
      "Mock provider active — dev only"
    );
  });

  it("renders nothing for a real provider", () => {
    useBootstrapStore
      .getState()
      .apply(bootstrapWith(aiStatus({ configured: true, provider_type: "openai" })));
    render(<AiMockChip />);
    expect(screen.queryByTestId("ai-mock-chip")).not.toBeInTheDocument();
  });
});
