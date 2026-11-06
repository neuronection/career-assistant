import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { SegmentedTabs } from "@/components/ui";
import { SettingsSectionCard } from "@/components/settings/SettingsSectionCard";
import { MappingTriageView } from "@/components/settings/MappingTriageView";
import { MappingTypesSourcesView } from "@/components/settings/MappingTypesSourcesView";
import { MappingOverviewView } from "@/components/settings/MappingOverviewView";
import { MappingRunsView } from "@/components/settings/MappingRunsView";
import { MappingQualityView } from "@/components/settings/MappingQualityView";

export const MAPPING_VIEWS = [
  "overview",
  "triage",
  "types-sources",
  "runs",
  "quality",
] as const;

export type MappingView = (typeof MAPPING_VIEWS)[number];

export function parseMappingView(raw: string | null): MappingView {
  return (MAPPING_VIEWS as readonly string[]).includes(raw ?? "")
    ? (raw as MappingView)
    : "overview";
}

/**
 * Tools → Mappings: the job-post → job-type mapping operations console
 * (plan 205). Admin-only; the views are URL-synced via ?view= under the
 * contract section ?section=mappings.
 */
export function MappingManagementSection() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const viewFromUrl = searchParams.get("view");
  const activeView = parseMappingView(viewFromUrl);

  useEffect(() => {
    const expected = activeView === "overview" ? null : activeView;
    if (viewFromUrl === expected) return;
    const next = new URLSearchParams(searchParams);
    if (expected) next.set("view", expected);
    else next.delete("view");
    setSearchParams(next, { replace: true });
  }, [viewFromUrl, activeView, searchParams, setSearchParams]);

  const setView = (view: MappingView) => {
    const next = new URLSearchParams(searchParams);
    if (view === "overview") next.delete("view");
    else next.set("view", view);
    setSearchParams(next, { replace: true });
  };

  return (
    <div className="space-y-6" data-testid="mappings-section">
      <SettingsSectionCard
        name="mappings"
        title={t("mappingsConsole.title")}
        description={t("mappingsConsole.subtitle")}
      >
        <SegmentedTabs
          ariaLabel={t("mappingsConsole.viewsAria")}
          className="max-w-xl"
          items={MAPPING_VIEWS.map((view) => ({
            value: view,
            label: t(`mappingsConsole.view.${view}`),
          }))}
          value={activeView}
          onValueChange={(next) => setView(next as MappingView)}
        />
      </SettingsSectionCard>
      <div data-testid={`mappings-view-${activeView}`}>
        {activeView === "overview" && <MappingOverviewView />}
        {activeView === "triage" && <MappingTriageView />}
        {activeView === "types-sources" && <MappingTypesSourcesView />}
        {activeView === "runs" && <MappingRunsView />}
        {activeView === "quality" && <MappingQualityView />}
      </div>
    </div>
  );
}
