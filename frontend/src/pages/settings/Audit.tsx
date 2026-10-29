import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Activity } from "lucide-react";
import type { AuditWindow } from "@/api/audit";
import { SegmentedTabs } from "@/components/ui";
import { SettingsPage } from "@/components/settings/SettingsPage";
import { OverviewTab } from "@/components/audit/OverviewTab";
import { AiActivityTab } from "@/components/audit/AiActivityTab";
import { SecurityTab } from "@/components/audit/SecurityTab";

export type AuditTab = "overview" | "ai" | "security";

// Exported for the tab-param tests (the repo-wide ?tab= pattern).
export const AUDIT_TABS: readonly AuditTab[] = ["overview", "ai", "security"];

export function parseAuditTab(raw: string | null): AuditTab {
  return (AUDIT_TABS as readonly string[]).includes(raw ?? "")
    ? (raw as AuditTab)
    : "overview";
}

export function parseAuditWindow(raw: string | null): AuditWindow {
  return raw === "7d" || raw === "30d" ? raw : "24h";
}

/** The audit & monitoring surface (plan 151): overview metrics, the AI
 * ledger and the security trail — tabs URL-synced via `?tab=`. */
export function Audit() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const tabFromUrl = searchParams.get("tab");
  const activeTab = parseAuditTab(tabFromUrl);
  const [window, setWindow] = useState<AuditWindow>(
    parseAuditWindow(searchParams.get("window")),
  );

  useEffect(() => {
    const expectedTab = activeTab === "overview" ? null : activeTab;
    const expectedWindow = window !== "24h" && activeTab !== "ai" ? window : null;
    if (tabFromUrl === expectedTab && searchParams.get("window") === expectedWindow) return;
    const next = new URLSearchParams(searchParams);
    if (expectedTab) next.set("tab", expectedTab);
    else next.delete("tab");
    if (expectedWindow) next.set("window", expectedWindow);
    else next.delete("window");
    setSearchParams(next, { replace: true });
  }, [tabFromUrl, activeTab, window, searchParams, setSearchParams]);

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
          {activeTab !== "ai" && (
            <SegmentedTabs
              ariaLabel={t("audit.windowAria")}
              items={
                [
                  { value: "24h", label: t("audit.window.24h") },
                  { value: "7d", label: t("audit.window.7d") },
                  { value: "30d", label: t("audit.window.30d") },
                ] as const
              }
              value={window}
              onValueChange={(next) => setWindow(next as AuditWindow)}
            />
          )}
        </div>

        {activeTab === "overview" && <OverviewTab window={window} />}
        {activeTab === "ai" && <AiActivityTab />}
        {activeTab === "security" && <SecurityTab window={window} />}
      </section>
    </SettingsPage>
  );
}
