import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { settingsNav } from "@/config/settingsNav";
import { AI_TABS } from "@/pages/settings/AIConfig";
import { TOOLS_TAB_SECTIONS } from "@/pages/settings/ToolsConfig";

// Settings-structure conformance wall (ADR-0033 / plan 27): the settings
// nav in this app must match the family contract vendored at
// contracts/settings-map.json. Placement changes go through the dev
// canonical copy first — never by editing the vendored file (which
// scripts/verify-wiring.sh keeps byte-identical) or the nav arrays alone.
const map = JSON.parse(
  readFileSync(
    join(__dirname, "..", "..", "..", "contracts", "settings-map.json"),
    "utf8",
  ),
) as {
  domains?: {
    id: string;
    definition: string;
    home?: { tab: string; section: string | null };
    adopters?: Record<string, string>;
  }[];
  products: Record<
    string,
    {
      tabs: {
        id: string;
        group: string;
        admin?: boolean;
        sections?: { id: string; domains: string[]; status?: string }[];
      }[];
    }
  >;
};

const declared = map.products["career-assistant"].tabs;

const navIds = settingsNav.map((item) => item.to.replace("/settings/", ""));
const navAdminFlags = new Map(
  settingsNav.map((item) => [item.to.replace("/settings/", ""), Boolean(item.adminOnly)]),
);

const declaredSections = (tabId: string) =>
  (declared.find((tab) => tab.id === tabId)?.sections ?? []).map((section) => section.id);

describe("settings-map contract", () => {
  it("the vendored map declares career-assistant's tabs exactly as shipped", () => {
    expect(declared.map((tab) => tab.id)).toEqual(navIds);
  });

  it("admin-only gating matches between the map and the nav registry", () => {
    for (const tab of declared) {
      expect(navAdminFlags.get(tab.id)).toBe(Boolean(tab.admin));
    }
  });

  // Plan 148: the app rail groups tabs into display sections derived from
  // the contract's domain groups (app+user → personal, ai/tools → aiTools,
  // automations, app+admin → administration) and the runs stay contiguous.
  it("rail display sections derive from the contract groups and stay contiguous", () => {
    const expectedSection = (tab: (typeof declared)[number]) => {
      if (tab.group === "ai" || tab.group === "tools") return "aiTools";
      if (tab.group === "automations") return "automation";
      return tab.admin ? "administration" : "personal";
    };
    for (const tab of declared) {
      const item = settingsNav.find((entry) => entry.to === `/settings/${tab.id}`);
      expect(item?.sectionKey, `section for ${tab.id}`).toBe(expectedSection(tab));
    }
    const runs: string[] = [];
    for (const item of settingsNav) {
      if (runs[runs.length - 1] !== item.sectionKey) runs.push(item.sectionKey);
    }
    expect(runs).toEqual(["personal", "aiTools", "automation", "administration"]);
  });

  it("the declared ai tab sections match the app's AI tabs", () => {
    expect(declaredSections("ai")).toEqual([...AI_TABS]);
  });

  it("the declared tools tab sections match the app's tools sections", () => {
    expect(declaredSections("tools")).toEqual([...TOOLS_TAB_SECTIONS]);
  });

  // INV-1/INV-2 (enforced part): aligned sections host only their own
  // group's domains.
  it("the ai tab hosts only ai.* domains (web search never drifts back in)", () => {
    const ai = declared.find((tab) => tab.id === "ai");
    expect(ai).toBeDefined();
    for (const section of ai!.sections ?? []) {
      expect(section.status ?? "aligned").toBe("aligned");
      for (const domain of section.domains) {
        expect(domain.startsWith("ai.")).toBe(true);
      }
    }
  });

  it("tools sections host only tools.* domains", () => {
    const tools = declared.find((tab) => tab.id === "tools");
    expect(tools).toBeDefined();
    for (const section of tools!.sections ?? []) {
      expect(section.status ?? "aligned").toBe("aligned");
      for (const domain of section.domains) {
        expect(domain.startsWith("tools.")).toBe(true);
      }
    }
  });

  // plan 32 Phase 1 (D17): the tools.connectors row broadened to job-source
  // connectors — the nav conformance pins the broadening so the row can
  // never silently shrink back to MCP-only.
  // plan 154: the connectors domain narrowed to the MCP server surface and
  // job-source ingestion split into its own domain.
  // plan 186: that combined sources domain split again into
  // tools.job-sources + tools.extensions. The UI section split is plan 186's
  // own step, so the shipped `sources` section temporarily hosts both
  // domains; the pins below keep the domains split and forbid tools.sources
  // from returning while the section id stays stable.
  it("tools.connectors is the MCP server surface; job sources and extensions are split domains", () => {
    const domains = map.domains ?? [];
    const connectors = domains.find((entry) => entry.id === "tools.connectors");
    expect(connectors).toBeDefined();
    expect(connectors!.definition).toMatch(/MCP server/i);
    expect(connectors!.home?.tab).toBe("tools");
    expect(connectors!.home?.section).toBe("mcp");

    const jobSources = domains.find((entry) => entry.id === "tools.job-sources");
    expect(jobSources).toBeDefined();
    expect(jobSources!.definition).toMatch(/job-source connector/i);
    expect(jobSources!.home?.section).toBe("job-sources");
    expect(jobSources!.adopters?.["career-assistant"]).toMatch(/plan 186/);

    const extensions = domains.find((entry) => entry.id === "tools.extensions");
    expect(extensions).toBeDefined();
    expect(extensions!.definition).toMatch(/extension sources/i);
    expect(extensions!.home?.section).toBe("extensions");
    expect(extensions!.adopters?.["career-assistant"]).toMatch(/plan 186/);

    // The plan-186 domain split must never leave the retired combined domain
    // behind; the section itself still hosts both domains until the UI split.
    expect(domains.find((entry) => entry.id === "tools.sources")).toBeUndefined();

    const declaredTools = declared.find((tab) => tab.id === "tools");
    expect(declaredTools!.sections!.map((section) => section.id)).toEqual([
      "web-search",
      "mcp",
      "sources",
    ]);
    const sourcesSection = declaredTools!.sections!.find((section) => section.id === "sources");
    expect(sourcesSection!.domains).toEqual(["tools.job-sources", "tools.extensions"]);
  });

  it("automations is declared in the automations group", () => {
    const automations = declared.find((tab) => tab.id === "automations");
    expect(automations?.group).toBe("automations");
  });
});
