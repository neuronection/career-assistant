import { describe, expect, it } from "vitest";

import {
  DEFAULT_CATALOG_FILTERS,
  catalogActiveChips,
  catalogApiParams,
  catalogParams,
  countActiveCatalogFilters,
  parseCatalogParams,
  removeCatalogChip,
  type CatalogFilters,
} from "@/features/catalog/catalogParams";

function filters(overrides: Partial<CatalogFilters> = {}): CatalogFilters {
  return { ...DEFAULT_CATALOG_FILTERS, ...overrides };
}

describe("catalogParams", () => {
  it("round-trips multi-value CSV axes and skill levels", () => {
    const params = new URLSearchParams(
      [
        "family=tech",
        "skills=programming@6,sql",
        "skill_exclude=excel",
        "skill_mode=any",
        "skill_min_level=4",
        "education=bachelor,master",
        "education_exclude=doctorate",
        "education_min=bachelor",
        "demand=hot,growing",
        "demand_exclude=declining",
        "salary_min=40000",
        "salary_max=90000",
        "contract=permanent",
        "contract_exclude=internship",
        "schedule=shift_work",
        "schedule_exclude=nights",
        "travel=none",
        "travel_exclude=frequent",
        "environment=office,remote",
        "environment_exclude=field",
        "experience_max_years=3",
        "has_roles=1",
        "interests=technology-software",
        "interest_exclude=healthcare",
        "q=nurse",
        "sort=open_roles",
      ].join("&")
    );
    const parsed = parseCatalogParams(params);
    expect(parsed.skills).toEqual([
      { key: "programming", level: 6 },
      { key: "sql", level: null },
    ]);
    expect(parsed.skillMode).toBe("any");
    expect(parsed.minLevel).toBe(4);
    expect(parsed.education).toEqual(["bachelor", "master"]);
    expect(parsed.demand).toEqual(["hot", "growing"]);
    expect(parsed.salaryMin).toBe("40000");
    expect(parsed.hasRoles).toBe(true);
    expect(parsed.sort).toBe("open_roles");

    const serialized = catalogParams(parsed);
    expect(serialized.get("family")).toBe("tech");
    expect(serialized.get("skills")).toBe("programming@6,sql");
    expect(serialized.get("education")).toBe("bachelor,master");
    expect(serialized.get("has_roles")).toBe("1");
    expect(serialized.get("sort")).toBe("open_roles");
    expect(parseCatalogParams(serialized)).toEqual(parsed);
  });

  it("canonicalizes unknown or invalid values away", () => {
    const parsed = parseCatalogParams(
      new URLSearchParams(
        [
          "nonsense=1",
          "skills=python@99,python@4",
          "education=moon",
          "demand=explosive",
          "sort=fit",
          "salary_min=-5",
          "has_roles=maybe",
          "skill_min_level=99",
        ].join("&")
      )
    );
    expect(parsed.skills).toEqual([{ key: "python", level: 4 }]);
    expect(parsed.education).toEqual([]);
    expect(parsed.demand).toEqual([]);
    expect(parsed.sort).toBe("title");
    expect(parsed.salaryMin).toBe("");
    expect(parsed.hasRoles).toBeNull();
    expect(parsed.minLevel).toBeNull();

    const serialized = catalogParams(parsed);
    expect(serialized.get("nonsense")).toBeNull();
    expect(serialized.get("education")).toBeNull();
    expect(serialized.get("sort")).toBeNull();
  });

  it("serializes an empty filter set to no params", () => {
    expect(catalogParams(DEFAULT_CATALOG_FILTERS).toString()).toBe("");
  });

  it("maps URL state onto the API query contract", () => {
    const api = catalogApiParams(
      filters({
        q: "nurse",
        family: "tech",
        skills: [{ key: "programming", level: 6 }],
        skillsExclude: ["excel"],
        skillMode: "any",
        minLevel: 4,
        salaryMin: "40000",
        salaryMax: "90000",
        experienceMax: "3",
        hasRoles: false,
        sort: "salary",
      })
    );
    expect(api).toMatchObject({
      q: "nurse",
      family_key: "tech",
      skills: "programming@6",
      skill_exclude: "excel",
      skill_mode: "any",
      skill_min_level: 4,
      salary_min: 40000,
      salary_max: 90000,
      experience_max_years: 3,
      has_roles: false,
      sort: "salary",
      with_facets: true,
      page_size: 100,
    });
    expect(catalogApiParams(filters(), false).with_facets).toBe(false);
  });
});

describe("catalog active filters", () => {
  const active = filters({
    q: "nurse",
    family: "tech",
    skills: [{ key: "python", level: 6 }],
    skillsExclude: ["excel"],
    minLevel: 4,
    education: ["bachelor"],
    demand: ["hot"],
    salaryMin: "40000",
    hasRoles: true,
    sort: "salary",
  });

  it("counts every active axis but not the sort", () => {
    expect(countActiveCatalogFilters(active)).toBe(9);
  });

  it("builds labelled summary chips", () => {
    const chips = catalogActiveChips(active);
    expect(chips.map((chip) => chip.axis)).toEqual([
      "q",
      "family",
      "skills",
      "skills",
      "minLevel",
      "education",
      "demand",
      "salary",
      "hasRoles",
    ]);
    const excludedSkill = chips.find(
      (chip) => chip.axis === "skills" && chip.kind === "exclude"
    );
    expect(excludedSkill?.label).toBe("− excel");
    const education = chips.find((chip) => chip.axis === "education");
    expect(education?.labelKey).toBe("catalog.facetValue.bachelor");
    const roles = chips.find((chip) => chip.axis === "hasRoles");
    expect(roles?.labelKey).toBe("catalog.chips.hasRoles");
  });

  it("removes a chip without clearing unrelated axes", () => {
    expect(removeCatalogChip(active, catalogActiveChips(active)[7])).toEqual({
      salaryMin: "",
    });
    const lastSkill = removeCatalogChip(
      filters({ skills: [{ key: "python", level: 6 }], minLevel: 4 }),
      catalogActiveChips(
        filters({ skills: [{ key: "python", level: 6 }], minLevel: 4 })
      ).find((chip) => chip.axis === "skills")!
    );
    expect(lastSkill).toEqual({ skills: [], minLevel: null });
    expect(
      removeCatalogChip(active, catalogActiveChips(active).find((chip) => chip.axis === "hasRoles")!)
    ).toEqual({ hasRoles: null });
  });
});
