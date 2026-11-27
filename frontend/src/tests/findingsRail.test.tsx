import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { FindingsRail } from "@/features/growth/components/FindingsRail";
import { DEFAULT_FINDINGS_FILTERS } from "@/features/growth/findingsFilterState";
import type { FindingFeedFacets } from "@/api/autopilot";

const SOURCES = [{ key: "board-postings", label: "board-postings (3)" }];

function facets(overrides: Partial<FindingFeedFacets> = {}): FindingFeedFacets {
  return {
    goal: {},
    source: {},
    seniority: {},
    state: { open: 0, dismissed: 0 },
    ...overrides,
  };
}

describe("FindingsRail counts", () => {
  it("renders no count for a source missing from the facets", () => {
    render(
      <FindingsRail
        filters={{ ...DEFAULT_FINDINGS_FILTERS, source: "board-postings" }}
        facets={facets()}
        sources={SOURCES}
        onChange={vi.fn()}
        onClear={vi.fn()}
      />
    );
    const chip = screen.getByTestId("source-board-postings");
    expect(chip).toHaveTextContent("board-postings");
    expect(chip.querySelector("bdi")).toBeNull();
    expect(chip).toHaveAccessibleName("board-postings (3)");
  });

  it("keeps the facet count on the chip, never in the section's active slot", () => {
    render(
      <FindingsRail
        filters={{ ...DEFAULT_FINDINGS_FILTERS, source: "board-postings" }}
        facets={facets({ source: { "board-postings": 3 } })}
        sources={SOURCES}
        onChange={vi.fn()}
        onClear={vi.fn()}
      />
    );
    expect(screen.getByTestId("source-board-postings")).toHaveTextContent("3");
    expect(document.querySelector('[data-as="filter-section-count"]')).toBeNull();
  });
});
