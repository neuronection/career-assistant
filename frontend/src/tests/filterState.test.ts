import { describe, expect, it } from "vitest";

import {
  buildSummaryChips,
  countActiveFilters,
  decodeFilterSpec,
  encodeFilterSpec,
  removeChip,
} from "@/features/postings/components/postings/filterState";
import { emptyFilterSpec, type FilterSpec } from "@/api/postings";

function withSkills(skills: Partial<FilterSpec["skills"]>): FilterSpec {
  const base = emptyFilterSpec();
  return { ...base, skills: { ...base.skills, ...skills } };
}

describe("filterState", () => {
  it("empty spec has zero active filters", () => {
    expect(countActiveFilters(emptyFilterSpec())).toBe(0);
    expect(buildSummaryChips(emptyFilterSpec())).toEqual([]);
  });

  it("counts every active axis", () => {
    const spec = {
      ...emptyFilterSpec(),
      skills: { ...emptyFilterSpec().skills, include: ["python"], min_level: 5 },
      salary: { min: 50000, max: null, currency: null },
      work_mode: { include: ["remote"], exclude: [] },
    };
    expect(countActiveFilters(spec)).toBe(4);
  });

  it("builds bound and exclude chips for seniority range", () => {
    const spec = {
      ...emptyFilterSpec(),
      seniority: { min: "senior", max: null, exclude: ["intern"] },
    };
    const chips = buildSummaryChips(spec);
    expect(chips).toHaveLength(2);
    expect(chips[0].kind).toBe("bound");
    expect(chips[0].label).toBe("≥ senior");
    expect(chips[1].kind).toBe("exclude");
    expect(chips[1].label).toBe("− intern");
  });

  it("removes a chip by value", () => {
    const spec = withSkills({ include: ["python", "sql"] });
    const chips = buildSummaryChips(spec);
    const next = removeChip(spec, chips[0]);
    expect(next.skills.include).toEqual(["sql"]);
    expect(countActiveFilters(next)).toBe(1);
  });

  it("surfaces the skill expansion state as a removable chip", () => {
    const spec = withSkills({ include: ["programming"], expand: "related", hops: 2 });
    const expansion = buildSummaryChips(spec).find(
      (chip) => chip.kind === "flag" && chip.value.startsWith("expand:"),
    );
    expect(expansion?.label).toBe("+ related · 2 hops");
    if (!expansion) throw new Error("expansion chip missing");
    expect(removeChip(spec, expansion).skills.expand).toBe("off");
  });

  it("adds no expansion chip in exact mode or without an included skill", () => {
    const exact = withSkills({ include: ["programming"], expand: "off" });
    const empty = withSkills({ expand: "down" });
    expect(buildSummaryChips(exact).some((chip) => chip.value.startsWith("expand:"))).toBe(false);
    expect(buildSummaryChips(empty).some((chip) => chip.value.startsWith("expand:"))).toBe(false);
    expect(countActiveFilters(empty)).toBe(0);
  });

  it("clears min_level when the last included skill is removed", () => {
    const spec = withSkills({ include: ["python"], min_level: 5 });
    const include = buildSummaryChips(spec).find((chip) => chip.kind === "include");
    if (!include) throw new Error("include chip missing");
    const next = removeChip(spec, include);
    expect(next.skills.include).toEqual([]);
    expect(next.skills.min_level).toBeNull();
  });

  it("round-trips through URL encoding", () => {
    const spec = withSkills({ include: ["python"], exclude: ["java"], min_level: 7, hops: 2 });
    const encoded = encodeFilterSpec(spec);
    const decoded = decodeFilterSpec(encoded);
    expect(decoded).toEqual(spec);
  });

  it("fills expansion defaults for a URL spec written before the knob", () => {
    const legacy = btoa(
      encodeURIComponent(
        JSON.stringify({ v: 1, skills: { include: ["python"], exclude: [], min_level: null } }),
      ),
    );
    const decoded = decodeFilterSpec(legacy);
    expect(decoded?.skills).toEqual({
      include: ["python"],
      exclude: [],
      min_level: null,
      expand: "down",
      hops: 1,
    });
  });

  it("returns null for garbage encoded data", () => {
    expect(decodeFilterSpec("not-base64!!!")).toBeNull();
    expect(decodeFilterSpec("")).toBeNull();
    expect(decodeFilterSpec(null)).toBeNull();
  });
});
