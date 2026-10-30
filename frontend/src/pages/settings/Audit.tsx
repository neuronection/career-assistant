import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Activity } from "lucide-react";
import { SegmentedTabs } from "@/components/ui";
import { SettingsPage } from "@/components/settings/SettingsPage";
import { RangeFilter, rangeParams, type RangeValue } from "@/components/audit/RangeFilter";
import { OverviewTab } from "@/components/audit/OverviewTab";
import { AiActivityTab } from "@/components/audit/AiActivityTab";
import { SecurityTab } from "@/components/audit/SecurityTab";
import { JobsTab } from "@/components/audit/JobsTab";
import { ChangesTab } from "@/components/audit/ChangesTab";
import { UsageTab } from "@/components/audit/UsageTab";

export type AuditTab = "overview" | "ai" | "usage" | "security" | "jobs" | "changes";

// Exported for the tab-param tests (the repo-wide ?tab= pattern).
export const AUDIT_TABS: readonly AuditTab[] = [
  "overview",
  "ai",
  "usage",
  "security",
  "jobs",
  "changes",
];

export function parseAuditTab(raw: string | null): AuditTab {
  return (AUDIT_TABS as readonly string[]).includes(raw ?? "")
    ? (raw as AuditTab)
    : "overview";
}

export function parseAuditWindow(raw: string | null): RangeValue["window"] {
  if (raw === "7d" || raw === "30d") return raw;
  return "24h";
}

/** The audit & monitoring surface (plans 151-152): overview metrics, the
 * AI ledger, the security trail, jobs & runs and the data-change journal
 * — tabs URL-synced via `?tab=`. */
export function Audit() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const tabFromUrl = searchParams.get("tab");
  const activeTab = parseAuditTab(tabFromUrl);
  const [range, setRange] = useState<RangeValue>({
    window: parseAuditWindow(searchParams.get("window")),
    from: "",
    to: "",
  });

  useEffect(() => {
    const expectedTab = activeTab === "overview" ? null : activeTab;
    const expectedWindow =
      range.window !== "24h" && range.window !== "custom" && activeTab !== "ai"
        ? range.window
        : null;
    if (tabFromUrl === expectedTab && searchParams.get("window") === expectedWindow) return;
    const next = new URLSearchParams(searchParams);
    if (expectedTab) next.set("tab", expectedTab);
    else next.delete("tab");
    if (expectedWindow) next.set("window", expectedWindow);
    else next.delete("window");
    setSearchParams(next, { replace: true });
  }, [tabFromUrl, activeTab, range, searchParams, setSearchParams]);

  const setActive = (tab: AuditTab) => {
    const next = new URLSearchParams(searchParams);
    if (tab === "overview") next.delete("tab");
    else next.set("tab", tab);
    setSearchParams(next, { replace: true });
  };

  return (
    <SettingsPage
      icon={Activity}
      title={t("settingsNav.audit.label")}
      description={t("settingsNav.audit.description")}
    >
      <section id="s-overview" className="scroll-mt-4">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <SegmentedTabs
            ariaLabel={t("audit.tabsAria")}
            items={AUDIT_TABS.map((tab) => ({
              value: tab,
              label: t(`audit.tab.${tab}`),
            }))}
            value={activeTab}
            onValueChange={(next) => setActive(next as AuditTab)}
          />
          {(activeTab === "overview" || activeTab === "security") && (
            <RangeFilter
              value={range}
              onChange={setRange}
              testId="audit-page-range"
            />
          )}
        </div>

        {activeTab === "overview" && <OverviewTab range={rangeParams(range)} />}
        {activeTab === "ai" && <AiActivityTab />}
        {activeTab === "usage" && <UsageTab range={rangeParams(range)} />}
        {activeTab === "security" && (
          <SecurityTab range={rangeParams(range)} />
        )}
        {activeTab === "jobs" && <JobsTab />}
        {activeTab === "changes" && <ChangesTab />}
      </section>
    </SettingsPage>
  );
}
