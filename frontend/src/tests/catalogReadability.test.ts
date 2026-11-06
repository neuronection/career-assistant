import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const srcRoot = join(__dirname, "..");

const CATALOG_SURFACE = [
  "features/catalog/pages/Catalog.tsx",
  "features/catalog/components/catalog/CatalogTree.tsx",
  "features/catalog/components/catalog/CatalogFilterRail.tsx",
  "features/catalog/components/JobCard.tsx",
  "features/postings/components/RecentSearches.tsx",
  "components/cards/CardSpec.tsx",
  "components/cards/CardMeta.tsx",
  "components/cards/ChipRow.tsx",
  "components/skills/SkillTag.tsx",
];

function read(path: string): string {
  return readFileSync(join(srcRoot, path), "utf8");
}

describe("catalog readability floor", () => {
  it("never renders text below 11px on the catalog surface", () => {
    const offenders: string[] = [];
    for (const path of CATALOG_SURFACE) {
      for (const match of read(path).matchAll(/text-\[(\d+(?:\.\d+)?)px\]/g)) {
        if (Number(match[1]) < 11) offenders.push(`${path}: ${match[0]}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe("catalog container layout", () => {
  it("uses no viewport column breakpoints", () => {
    const offenders: string[] = [];
    for (const path of CATALOG_SURFACE) {
      for (const match of read(path).matchAll(
        /\b(?:sm|md|lg|xl|2xl):(?:grid-cols-|col-span-|columns-)/g
      )) {
        offenders.push(`${path}: ${match[0]}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("renders the /postings container template and the card grid", () => {
    const tree = read("features/catalog/components/catalog/CatalogTree.tsx");
    expect(tree).toContain("ca-stats-page");
    expect(tree).toContain("ca-stats-cols");
    expect(tree).toContain("ca-card-page");
    expect(tree).toContain("ca-card-grid");
    expect(tree).not.toContain("SettingsShell");
  });
});
