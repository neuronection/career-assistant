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

  it("automations is declared in the automations group", () => {
    const automations = declared.find((tab) => tab.id === "automations");
    expect(automations?.group).toBe("automations");
  });
});
