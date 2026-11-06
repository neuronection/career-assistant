import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ActiveFilterChips } from "@/components/filters/ActiveFilterChips";
import { DEFAULT_FILTERS } from "@/features/catalog/exploreParams";
import { exploreFilterChips } from "@/features/postings/components/postings/presetSummary";
import {
  DEFAULT_FILTERS as DEFAULT_COMPANY_FILTERS,
  companiesFilterChips,
} from "@/features/companies/companiesParams";
import {
  DEFAULT_FINDINGS_FILTERS,
  findingsFilterChips,
} from "@/features/growth/findingsFilterState";

const t = (key: string, options?: Record<string, unknown>) => {
  const parts = Object.entries(options ?? {}).map(([name, value]) => `${name}=${String(value)}`);
  return parts.length ? `${key}(${parts.join(",")})` : key;
};

describe("ActiveFilterChips", () => {
  it("renders nothing without chips", () => {
    const { container } = render(
      <ActiveFilterChips chips={[]} onRemove={vi.fn()} testId="chips" />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders one removable button per chip", () => {
    const onRemove = vi.fn();
    render(
      <ActiveFilterChips
        chips={[
          { key: "a", label: "Alpha" },
          { key: "b", label: "Beta" },
        ]}
        onRemove={onRemove}
        testId="chips"
        chipTestId={(key) => `chip-${key}`}
      />
    );
    expect(screen.getByTestId("chips")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("chip-a"));
    expect(onRemove).toHaveBeenCalledWith("a");
  });
});

describe("exploreFilterChips", () => {
  const filters = {
    ...DEFAULT_FILTERS,
    q: "nurse",
    seniority: ["mid"],
    skills: [{ key: "sql", level: 3 }],
    saved: true,
  };

  it("builds one chip per applied value", () => {
    const chips = exploreFilterChips(filters, t);
    expect(chips.map((chip) => chip.key)).toEqual([
      "q",
      "skill-sql",
      "seniority-mid",
      "saved",
    ]);
    expect(chips.find((chip) => chip.key === "skill-sql")?.label).toContain("sql ≥ 3");
  });

  it("removes exactly the value the chip owns", () => {
    const chips = exploreFilterChips(filters, t);
    expect(chips.find((chip) => chip.key === "seniority-mid")?.patch).toEqual({
      seniority: [],
    });
    expect(chips.find((chip) => chip.key === "q")?.patch).toEqual({ q: "" });
    expect(chips.find((chip) => chip.key === "saved")?.patch).toEqual({ saved: false });
  });

  it("marks excludes with a leading minus", () => {
    const chips = exploreFilterChips(
      { ...DEFAULT_FILTERS, seniorityExclude: ["senior"] },
      t
    );
    expect(chips[0].label.startsWith("−")).toBe(true);
    expect(chips[0].patch).toEqual({ seniorityExclude: [] });
  });
});

describe("companiesFilterChips", () => {
  const filters = {
    ...DEFAULT_COMPANY_FILTERS,
    status: "new" as const,
    industries: ["fintech"],
    minOpen: 5,
    location: "Athens",
  };

  it("labels facet values through the companies facet keys", () => {
    const chips = companiesFilterChips(filters, t);
    expect(chips.map((chip) => chip.key)).toEqual([
      "status",
      "industries-fintech",
      "min-open",
      "location",
    ]);
    expect(chips[1].label).toContain("companies.facet.industries.fintech");
  });

  it("removes one value without touching its siblings", () => {
    const chips = companiesFilterChips(
      { ...filters, industries: ["fintech", "health"] },
      t
    );
    expect(chips.find((chip) => chip.key === "industries-fintech")?.patch).toEqual({
      industries: ["health"],
    });
  });
});

describe("findingsFilterChips", () => {
  it("covers state, score bounds, toggles and context filters", () => {
    const chips = findingsFilterChips(
      {
        ...DEFAULT_FINDINGS_FILTERS,
        state: "all",
        minScore: 7,
        remote: true,
        postedWithin: "7d",
      },
      t
    );
    expect(chips.map((chip) => chip.key)).toEqual([
      "state",
      "min-score",
      "remote",
      "posted",
    ]);
    expect(chips.find((chip) => chip.key === "state")?.patch).toEqual({ state: "open" });
    expect(chips.find((chip) => chip.key === "posted")?.patch).toEqual({
      postedWithin: "",
    });
  });

  it("has no chip for the goal, run, view or sort context", () => {
    const chips = findingsFilterChips(
      {
        ...DEFAULT_FINDINGS_FILTERS,
        goal: "g1",
        runId: "r1",
        view: "byrun",
        sort: "score",
      },
      t
    );
    expect(chips).toEqual([]);
  });
});
