import { describe, expect, it } from "vitest";

import {
  countActive,
  DEFAULT_FILTERS,
  parseFilters,
  toParams,
  toSearchParams,
} from "@/features/companies/companiesParams";

describe("companies URL params", () => {
  it("round-trips the directory filters", () => {
    const filters = parseFilters(
      new URLSearchParams(
        "q=acme&status=new&work_mode=remote,hybrid&work_mode_exclude=onsite" +
          "&seniority=mid&seniority_exclude=junior&employment=full_time" +
          "&employment_exclude=internship&industry=fintech&min_open=5" +
          "&location=Athens&sort=recent"
      )
    );
    expect(filters).toMatchObject({
      q: "acme",
      status: "new",
      workMode: ["remote", "hybrid"],
      workModeExclude: ["onsite"],
      seniority: ["mid"],
      seniorityExclude: ["junior"],
      employment: ["full_time"],
      employmentExclude: ["internship"],
      industries: ["fintech"],
      minOpen: 5,
      location: "Athens",
      sort: "recent",
    });
    expect(parseFilters(toSearchParams(filters))).toEqual(filters);
  });

  it("drops unknown and invalid values", () => {
    const filters = parseFilters(
      new URLSearchParams("status=maybe&min_open=2&sort=bogus&who=me")
    );
    expect(filters.status).toBe("all");
    expect(filters.minOpen).toBe(0);
    expect(filters.sort).toBe("open_postings");
    expect(toSearchParams(filters).toString()).toBe("");
  });

  it("omits defaults and never sends the status to the API", () => {
    expect(toSearchParams(DEFAULT_FILTERS).toString()).toBe("");
    expect(toParams(DEFAULT_FILTERS)).toEqual({});
    expect(countActive(DEFAULT_FILTERS)).toBe(0);

    const filters = parseFilters(new URLSearchParams("status=new&min_open=3"));
    expect(toParams(filters)).toEqual({ min_open: 3 });
    expect(countActive(filters)).toBe(2);
  });
});
