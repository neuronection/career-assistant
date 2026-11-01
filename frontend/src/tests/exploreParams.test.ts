import { describe, expect, it } from "vitest";

import {
  countActive,
  DEFAULT_FILTERS,
  parseFilters,
  toParams,
  toSearchParams,
} from "@/features/catalog/exploreParams";

describe("explore URL params", () => {
  it("round-trips the full filter vocabulary", () => {
    const search =
      "q=backend&skills=programming:4,sql&skill_mode=any&skill_exclude=java" +
      "&posted_within=7d&salary_min=60000&seniority=mid,senior&seniority_exclude=junior" +
      "&remote_policy=remote&remote_policy_exclude=onsite&source=synth&source_exclude=rss" +
      "&contract=permanent&contract_exclude=internship&travel=none&travel_exclude=frequent" +
      "&schedule=nights&schedule_exclude=weekends&extracted_only=true&saved=true" +
      "&seen_exclude=true&sort=salary&org=Acme%2C+Inc.&org=Cohere";
    const filters = parseFilters(new URLSearchParams(search));
    const canonical = toSearchParams(filters);
    expect(parseFilters(canonical)).toEqual(filters);
    expect(canonical.get("sort")).toBe("salary");
    expect(canonical.getAll("org")).toEqual(["Acme, Inc.", "Cohere"]);
    expect(canonical.get("skills")).toBe("programming:4,sql");
    expect(canonical.get("seniority_exclude")).toBe("junior");
  });

  it("keeps commas inside organization names", () => {
    const filters = parseFilters(new URLSearchParams("org=Acme%2C+Inc.&org=Cohere"));
    expect(filters.orgs).toEqual(["Acme, Inc.", "Cohere"]);
    expect(toParams(filters).org).toEqual(["Acme, Inc.", "Cohere"]);
  });

  it("drops unknown, invalid and out-of-range values instead of failing", () => {
    const filters = parseFilters(
      new URLSearchParams(
        "sort=bogus&posted_within=1y&contract=dream_job&skills=:4,bad:99,good:11,ok:3&salary_min=-5&who=me"
      )
    );
    expect(filters.sort).toBe("fit");
    expect(filters.postedWithin).toBe("");
    expect(filters.contract).toEqual([]);
    expect(filters.skills).toEqual([{ key: "ok", level: 3 }]);
    expect(filters.salaryMin).toBe("");
    expect(toSearchParams(filters).toString()).toBe("skills=ok%3A3");
  });

  it("falls back to fit when relevance has no query", () => {
    expect(parseFilters(new URLSearchParams("sort=relevance")).sort).toBe("fit");
    expect(parseFilters(new URLSearchParams("sort=relevance&q=dev")).sort).toBe("relevance");
  });

  it("accepts the smart sort in the URL state and re-emits it", () => {
    const filters = parseFilters(new URLSearchParams("sort=smart&seen_exclude=true"));
    expect(filters.sort).toBe("smart");
    expect(toSearchParams(filters).get("sort")).toBe("smart");
    expect(parseFilters(new URLSearchParams("sort=bogus")).sort).toBe("fit");
  });

  it("omits defaults from the URL but keeps the state toggle count", () => {
    expect(toSearchParams(DEFAULT_FILTERS).toString()).toBe("");
    expect(countActive(DEFAULT_FILTERS)).toBe(0);
    const filters = parseFilters(new URLSearchParams("seen_exclude=true&saved=true"));
    expect(countActive(filters)).toBe(2);
    expect(toParams(filters)).toEqual({ saved: true, seen_exclude: true });
  });

  it("treats text booleans honestly", () => {
    for (const value of ["false", "0", "no", "off", ""]) {
      expect(parseFilters(new URLSearchParams(`saved=${value}`)).saved).toBe(false);
    }
    expect(parseFilters(new URLSearchParams("saved=1")).saved).toBe(true);
  });
});
