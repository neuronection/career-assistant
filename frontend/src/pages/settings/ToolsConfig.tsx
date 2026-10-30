import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { SegmentedTabs } from "@/components/ui";
import { WebSearchSection } from "@/components/settings/WebSearchSection";
import { McpServerSection } from "@/components/settings/McpServerSection";
import { SourcesSection } from "@/components/settings/SourcesSection";

type ToolsSection = "web-search" | "mcp" | "sources";

// Settings structure follows the family contract (contracts/settings-map.json,
// ADR-0033): tools.* domains live in the tools tab, never under AI
// configuration. Exported for the settings-map conformance test.
// Plan 154: the former connectors section split into mcp (the MCP server
// surface) and sources (job-source + extension ingestion); legacy
// ?section=connectors deep links resolve to mcp.
export const TOOLS_TAB_SECTIONS: readonly ToolsSection[] = [
  "web-search",
  "mcp",
  "sources",
];

export function parseToolsSection(raw: string | null): ToolsSection {
  if (raw === "connectors") return "mcp";
  return (TOOLS_TAB_SECTIONS as readonly string[]).includes(raw ?? "")
    ? (raw as ToolsSection)
    : "web-search";
}

/**
 * Tools configuration with URL-synced sections
 * (?section=web-search|mcp|sources). Admin-only (same gate the former
 * AI-config `web` tab had, plan 27 Phase 3).
 */
export function ToolsConfig() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const sectionFromUrl = searchParams.get("section");
  const activeSection = parseToolsSection(sectionFromUrl);

  useEffect(() => {
    const expected = activeSection === "web-search" ? null : activeSection;
    if (sectionFromUrl === expected) return;
    const next = new URLSearchParams(searchParams);
    if (expected) next.set("section", expected);
    else next.delete("section");
    setSearchParams(next, { replace: true });
  }, [sectionFromUrl, activeSection, searchParams, setSearchParams]);

  const setSection = (section: ToolsSection) => {
    const next = new URLSearchParams(searchParams);
    if (section === "web-search") next.delete("section");
    else next.set("section", section);
    setSearchParams(next, { replace: true });
  };

  return (
    <div className="space-y-6" data-testid="tools-config">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">{t("toolsSettings.title")}</h1>
          <p className="text-sm text-slate-500">{t("toolsSettings.subtitle")}</p>
        </div>
      </div>

      <SegmentedTabs
        ariaLabel={t("toolsSettings.sectionsAria")}
        className="max-w-md"
        items={TOOLS_TAB_SECTIONS.map((section) => ({
          value: section,
          label: t(`toolsSettings.section.${section}`),
        }))}
        value={activeSection}
        onValueChange={(next) => setSection(next as ToolsSection)}
      />

      {activeSection === "web-search" && <WebSearchSection />}
      {activeSection === "mcp" && <McpServerSection />}
      {activeSection === "sources" && <SourcesSection />}
    </div>
  );
}
