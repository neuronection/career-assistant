import { describe, expect, it } from "vitest";

import { DEFAULT_FILTERS, type Filters } from "@/features/catalog/exploreParams";
import {
  applyCardFilter,
  filterStateOf,
} from "@/features/postings/components/postings/cardFilterMenu";

const filters = (overrides: Partial<Filters> = {}): Filters => ({
  ...DEFAULT_FILTERS,
  skills: [{ key: "python", level: 4 }],
  skillsExclude: ["java"],
  orgs: ["Acme"],
  orgsExclude: ["Globex"],
  remotePolicy: ["remote"],
  remotePolicyExclude: ["onsite"],
  seniority: ["senior"],
  seniorityExclude: ["intern"],
  contract: ["full_time"],
  contractExclude: ["temporary"],
  ...overrides,
});

describe("filterStateOf", () => {
  it("maps every axis onto its include/exclude pair", () => {
    const f = filters();
    expect(filterStateOf(f, "skills", "python")).toBe("include");
    expect(filterStateOf(f, "skills", "java")).toBe("exclude");
    expect(filterStateOf(f, "skills", "rust")).toBeNull();
    expect(filterStateOf(f, "orgs", "Acme")).toBe("include");
    expect(filterStateOf(f, "orgs", "Globex")).toBe("exclude");
    expect(filterStateOf(f, "remotePolicy", "remote")).toBe("include");
    expect(filterStateOf(f, "seniority", "intern")).toBe("exclude");
    expect(filterStateOf(f, "contract", "full_time")).toBe("include");
  });
});

describe("applyCardFilter — skills axis", () => {
  it("include appends the key without level and drops the value from exclude", () => {
    const next = applyCardFilter(filters(), { axis: "skills", value: "rust", label: "Rust" }, "include");
    expect(next.skills).toEqual([
      { key: "python", level: 4 },
      { key: "rust", level: null },
    ]);
    expect(next.skillsExclude).toEqual(["java"]);
  });

  it("include preserves the stored level of an already-included skill", () => {
    const next = applyCardFilter(filters(), { axis: "skills", value: "python", label: "Python" }, "include");
    expect(next.skills).toEqual([{ key: "python", level: 4 }]);
    expect(next.skillsExclude).toEqual(["java"]);
  });

  it("exclude moves the key out of include and into exclude", () => {
    const next = applyCardFilter(filters(), { axis: "skills", value: "python", label: "Python" }, "exclude");
    expect(next.skills).toEqual([]);
    expect(next.skillsExclude).toEqual(["java", "python"]);
  });

  it("exclude of a non-included skill leaves the include list untouched", () => {
    const next = applyCardFilter(filters(), { axis: "skills", value: "rust", label: "Rust" }, "exclude");
    expect(next.skills).toEqual([{ key: "python", level: 4 }]);
    expect(next.skillsExclude).toEqual(["java", "rust"]);
  });

  it("clear removes the key from both lists", () => {
    const next = applyCardFilter(filters(), { axis: "skills", value: "java", label: "Java" }, "clear");
    expect(next.skills).toEqual([{ key: "python", level: 4 }]);
    expect(next.skillsExclude).toEqual([]);
  });
});

describe("applyCardFilter — enum axes", () => {
  it("include is mutually exclusive with exclude", () => {
    const next = applyCardFilter(filters(), { axis: "orgs", value: "Initech", label: "Initech" }, "include");
    expect(next.orgs).toEqual(["Acme", "Initech"]);
    expect(next.orgsExclude).toEqual(["Globex"]);
  });

  it("exclude drops the value from include", () => {
    const next = applyCardFilter(filters(), { axis: "seniority", value: "senior", label: "Senior" }, "exclude");
    expect(next.seniority).toEqual([]);
    expect(next.seniorityExclude).toEqual(["intern", "senior"]);
  });

  it("clear removes from both sides without duplicating", () => {
    const next = applyCardFilter(filters(), { axis: "remotePolicy", value: "onsite", label: "On-site" }, "clear");
    expect(next.remotePolicy).toEqual(["remote"]);
    expect(next.remotePolicyExclude).toEqual([]);
  });

  it("contract include/exclude round-trips the pair", () => {
    const next = applyCardFilter(filters(), { axis: "contract", value: "part_time", label: "Part-time" }, "exclude");
    expect(next.contract).toEqual(["full_time"]);
    expect(next.contractExclude).toEqual(["temporary", "part_time"]);
  });
});
