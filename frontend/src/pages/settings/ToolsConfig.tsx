import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { SegmentedTabs } from "@/components/ui";
import { WebSearchSection } from "@/components/settings/WebSearchSection";
import { ConnectorsSection } from "@/components/settings/ConnectorsSection";

type ToolsSection = "web-search" | "connectors";

// Settings structure follows the family contract (contracts/settings-map.json,
// ADR-0033): tools.* domains live in the tools tab, never under AI
// configuration. Exported for the settings-map conformance test.
export const TOOLS_TAB_SECTIONS: readonly ToolsSection[] = [
  "web-search",
  "connectors",
];

/**
 * Tools configuration with URL-synced sections (?section=web-search|connectors).
 * Admin-only (same gate the former AI-config `web` tab had, plan 27 Phase 3).
 */
export function ToolsConfig() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const sectionFromUrl = searchParams.get("section") as ToolsSection | null;
  const [activeSection, setActiveSection] = useState<ToolsSection>(
    sectionFromUrl && TOOLS_TAB_SECTIONS.includes(sectionFromUrl)
      ? sectionFromUrl
      : "web-search"
  );

  useEffect(() => {
    if (
      sectionFromUrl &&
      TOOLS_TAB_SECTIONS.includes(sectionFromUrl) &&
      sectionFromUrl !== activeSection
    ) {
      setActiveSection(sectionFromUrl);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sectionFromUrl]);

  const setSection = (section: ToolsSection) => {
    setActiveSection(section);
    navigate(
      section !== "web-search"
        ? { pathname: "/settings/tools", search: `?section=${section}` }
        : { pathname: "/settings/tools" },
      { replace: true }
    );
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
      {activeSection === "connectors" && <ConnectorsSection />}
    </div>
  );
}
