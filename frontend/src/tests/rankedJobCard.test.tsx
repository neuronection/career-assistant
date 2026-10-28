import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { RankedJobCard } from "@/features/catalog/components/RankedJobCard";
import type { RankedJob } from "@/types/wire";

function ranked(overrides: Partial<RankedJob> = {}): RankedJob {
  return {
    score: 7.4,
    fit_score: 8,
    ai_score: 7,
    user_score: 6,
    breakdown: {
      dimensions: {
        skills: { score: 8.8, weight: 3, detail: "covered" },
        location: { score: 5, weight: 1, detail: "same city" },
      },
      gates: [],
      specialist_dimension: null,
    },
    gated: false,
    gate_reasons: [],
    specialist_dimension: "skills",
    status: "considering",
    insight: null,
    job: {
      id: "j1",
      code: "backend-engineer",
      title: "Backend Engineer",
      short_description: "Builds services.",
      family_key: "technology",
      family_label: "Technology",
      status: "published",
      source: "seed",
      interests: [],
      skills: [],
      attributes: { demand: { outlook: "hot" } },
    },
    ...overrides,
  } as unknown as RankedJob;
}

function renderCard(item: RankedJob, props: Partial<Parameters<typeof RankedJobCard>[0]> = {}) {
  const handlers = {
    expanded: false,
    onToggleBreakdown: vi.fn(),
    onRate: vi.fn(),
    compareSelected: false,
    onToggleCompare: vi.fn(),
    ...props,
  };
  render(
    <MemoryRouter>
      <RankedJobCard item={item} {...handlers} />
    </MemoryRouter>
  );
  return handlers;
}

describe("RankedJobCard", () => {
  it("keeps the score trio and the match bubble", () => {
    renderCard(ranked());
    expect(screen.getByTestId("scores-backend-engineer")).toHaveTextContent("8.0");
    expect(screen.getByTestId("scores-backend-engineer")).toHaveTextContent("7.0");
    expect(screen.getByTestId("scores-backend-engineer")).toHaveTextContent("6");
    expect(screen.getByTestId("score-ring")).toHaveAttribute("data-score", "7.4");
  });

  it("shows specialist and gate chips", () => {
    renderCard(
      ranked({ gated: true, gate_reasons: ["salary_min"], specialist_dimension: "skills" })
    );
    expect(screen.getByText(/strong in/i)).toBeInTheDocument();
    expect(screen.getByText("salary_min")).toBeInTheDocument();
  });

  it("expands the breakdown through the why toggle", () => {
    const handlers = renderCard(ranked());
    fireEvent.click(screen.getByTestId("breakdown-toggle-backend-engineer"));
    expect(handlers.onToggleBreakdown).toHaveBeenCalledTimes(1);
  });

  it("renders the breakdown when expanded", () => {
    renderCard(ranked(), { expanded: true });
    expect(screen.getByTestId("fit-breakdown")).toHaveTextContent("Skills");
    expect(screen.getByTestId("fit-breakdown-detail")).toHaveTextContent(
      "Skills: covered"
    );
  });

  it("rates and compares from the action column", () => {
    const handlers = renderCard(ranked());
    fireEvent.click(screen.getByText(/interested/i));
    expect(handlers.onRate).toHaveBeenCalledWith("interested");
    fireEvent.click(screen.getByTestId("compare-add-backend-engineer"));
    expect(handlers.onToggleCompare).toHaveBeenCalledTimes(1);
  });
});
