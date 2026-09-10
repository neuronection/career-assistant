import { describe, expect, it, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

import { FitStaleBadge } from "@/components/FitStaleBadge";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import type { Bootstrap } from "@/types";

function bootstrap(partial: Partial<Bootstrap>): Bootstrap {
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
    ...partial,
  };
}

beforeEach(() => {
  useBootstrapStore.setState({ bootstrap: null, loaded: false });
});

describe("FitStaleBadge", () => {
  it("renders while fits are being recomputed", () => {
    useBootstrapStore.setState({
      bootstrap: bootstrap({ fit_stale: true }),
      loaded: true,
    });
    render(<FitStaleBadge />);
    expect(screen.getByTestId("fit-stale-badge")).toBeTruthy();
    expect(screen.getByText("Fits updating…")).toBeTruthy();
  });

  it("hides once the refit sweep has stamped fresh fits", () => {
    useBootstrapStore.setState({
      bootstrap: bootstrap({ fit_stale: false }),
      loaded: true,
    });
    render(<FitStaleBadge />);
    expect(screen.queryByTestId("fit-stale-badge")).toBeNull();
  });
});
