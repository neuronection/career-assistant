import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import {
  FirstRunSetupGate,
  shouldRedirectToSetup,
} from "@/features/profile/components/onboarding/FirstRunSetupGate";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import type { AiStatus, Bootstrap } from "@/types";

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

function bootstrap(ai: AiStatus | undefined): Bootstrap {
  const weights = { skills: 3, location: 3, experience: 3, education: 3, interests: 3, values: 3 };
  return {
    career_stage: "student",
    stage_source: "derived",
    features: { universities: true, grade_fields: true, education_step: true },
    suggested_scoring_weights: weights,
    effective_scoring_weights: weights,
    weights_overridden: false,
    ai,
  };
}

beforeEach(() => {
  useBootstrapStore.getState().reset();
});

describe("shouldRedirectToSetup", () => {
  it("sends an unconfigured first run to the setup step", () => {
    expect(shouldRedirectToSetup("/", aiStatus())).toBe(true);
    expect(shouldRedirectToSetup("/cv", aiStatus())).toBe(true);
  });

  it("stays out of the way once AI is configured or the step was skipped", () => {
    expect(shouldRedirectToSetup("/", aiStatus({ configured: true }))).toBe(false);
    expect(shouldRedirectToSetup("/", aiStatus({ setup_dismissed: true }))).toBe(false);
  });

  it("never bounces the onboarding flow, settings or about", () => {
    expect(shouldRedirectToSetup("/onboarding", aiStatus())).toBe(false);
    expect(shouldRedirectToSetup("/onboarding/setup", aiStatus())).toBe(false);
    expect(shouldRedirectToSetup("/settings/ai", aiStatus())).toBe(false);
    expect(shouldRedirectToSetup("/about", aiStatus())).toBe(false);
  });

  it("does nothing before the bootstrap payload lands", () => {
    expect(shouldRedirectToSetup("/", undefined)).toBe(false);
  });
});

describe("FirstRunSetupGate", () => {
  it("navigates a fresh unconfigured app to the setup step", async () => {
    useBootstrapStore.getState().apply(bootstrap(aiStatus()));
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route
            path="/"
            element={
              <>
                <FirstRunSetupGate />
                <div>dashboard</div>
              </>
            }
          />
          <Route path="/onboarding/setup" element={<div>setup-page</div>} />
        </Routes>
      </MemoryRouter>
    );
    expect(await screen.findByText("setup-page")).toBeInTheDocument();
  });

  it("leaves a configured app alone", () => {
    useBootstrapStore.getState().apply(bootstrap(aiStatus({ configured: true })));
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route
            path="/"
            element={
              <>
                <FirstRunSetupGate />
                <div>dashboard</div>
              </>
            }
          />
          <Route path="/onboarding/setup" element={<div>setup-page</div>} />
        </Routes>
      </MemoryRouter>
    );
    expect(screen.getByText("dashboard")).toBeInTheDocument();
    expect(screen.queryByText("setup-page")).not.toBeInTheDocument();
  });
});
