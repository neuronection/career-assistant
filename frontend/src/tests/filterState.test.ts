import { describe, expect, it } from "vitest";

import {
  buildSummaryChips,
  countActiveFilters,
  decodeFilterSpec,
  encodeFilterSpec,
  removeChip,
} from "@/features/postings/components/postings/filterState";
import { emptyFilterSpec } from "@/api/postings";

describe("filterState", () => {
  it("empty spec has zero active filters", () => {
    expect(countActiveFilters(emptyFilterSpec())).toBe(0);
    expect(buildSummaryChips(emptyFilterSpec())).toEqual([]);
  });

  it("counts every active axis", () => {
    const spec = {
      ...emptyFilterSpec(),
      skills: { include: ["python"], exclude: [], min_level: 5 },
      salary: { min: 50000, max: null, currency: null },
      work_mode: { include: ["remote"], exclude: [] },
    };
    expect(countActiveFilters(spec)).toBe(4);
  });

  it("builds include and exclude chips", () => {
    const spec = {
      ...emptyFilterSpec(),
      seniority: { include: ["senior"], exclude: ["intern"] },
    };
    const chips = buildSummaryChips(spec);
    expect(chips).toHaveLength(2);
    expect(chips[0].kind).toBe("include");
    expect(chips[1].kind).toBe("exclude");
  });

  it("removes a chip by value", () => {
    const spec = {
      ...emptyFilterSpec(),
      skills: { include: ["python", "sql"], exclude: [], min_level: null },
    };
    const chips = buildSummaryChips(spec);
    const next = removeChip(spec, chips[0]);
    expect(next.skills.include).toEqual(["sql"]);
    expect(countActiveFilters(next)).toBe(1);
  });

  it("round-trips through URL encoding", () => {
    const spec = {
      ...emptyFilterSpec(),
      skills: { include: ["python"], exclude: ["java"], min_level: 7 },
      salary: { min: 50000, max: 120000, currency: "EUR" },
    };
    const encoded = encodeFilterSpec(spec);
    const decoded = decodeFilterSpec(encoded);
    expect(decoded).toEqual(spec);
  });

  it("returns null for garbage encoded data", () => {
    expect(decodeFilterSpec("not-base64!!!")).toBeNull();
    expect(decodeFilterSpec("")).toBeNull();
    expect(decodeFilterSpec(null)).toBeNull();
  });
});
