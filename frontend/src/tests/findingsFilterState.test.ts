import { describe, expect, it } from "vitest";

import {
  DEFAULT_FINDINGS_FILTERS,
  countActiveFindingsFilters,
  parseFindingsFilters,
  toFeedParams,
  toFindingsSearchParams,
} from "@/features/growth/findingsFilterState";

describe("findingsFilterState", () => {
  it("round-trips every axis through the URL and drops defaults", () => {
    const filters = {
      ...DEFAULT_FINDINGS_FILTERS,
      state: "dismissed" as const,
      latest: false,
      hideApplied: true,
      sort: "score" as const,
      minScore: 7,
      coverageMin: 2,
      org: "Acme, Inc.",
      source: "board",
      seniority: "senior" as const,
      remote: true,
      postedWithin: "30d",
      goal: "g1",
      view: "byrun" as const,
    };
    const round = parseFindingsFilters(toFindingsSearchParams(filters));
    expect(round).toEqual(filters);
    expect(toFindingsSearchParams(round).get("min_score")).toBe("7");

    const defaults = toFindingsSearchParams(DEFAULT_FINDINGS_FILTERS);
    expect(defaults.toString()).toBe("");
  });

  it("falls back to defaults on unknown or malformed values", () => {
    const parsed = parseFindingsFilters(
      new URLSearchParams(
        "state=bogus&sort=nope&min_score=99&coverage_min=abc&posted_within=2h&seniority=ceo&view=x"
      )
    );
    expect(parsed.state).toBe("open");
    expect(parsed.sort).toBe("newest");
    expect(parsed.minScore).toBeNull();
    expect(parsed.coverageMin).toBeNull();
    expect(parsed.postedWithin).toBe("");
    expect(parsed.seniority).toBeNull();
    expect(parsed.view).toBe("flat");
  });

  it("counts active filters against the defaults", () => {
    expect(countActiveFindingsFilters(DEFAULT_FINDINGS_FILTERS)).toBe(0);
    const one = { ...DEFAULT_FINDINGS_FILTERS, minScore: 5 };
    expect(countActiveFindingsFilters(one)).toBe(1);
    const several = {
      ...one,
      state: "all" as const,
      latest: false,
      hideApplied: true,
      org: " acme ",
      remote: true,
    };
    expect(countActiveFindingsFilters(several)).toBe(6);
  });

  it("maps the filter set onto the feed endpoint's params", () => {
    const params = toFeedParams({
      ...DEFAULT_FINDINGS_FILTERS,
      minScore: 4,
      org: "  Acme  ",
      hideApplied: true,
      goal: null,
    });
    expect(params).toEqual({
      goal_id: undefined,
      state: "open",
      latest_per_posting: true,
      sort: "newest",
      min_score: 4,
      coverage_min: undefined,
      org: "Acme",
      source: undefined,
      seniority: undefined,
      remote: undefined,
      posted_within: undefined,
      hide_applied: true,
    });
  });
});
