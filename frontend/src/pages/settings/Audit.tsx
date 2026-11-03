import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Activity } from "lucide-react";
import { SegmentedTabs } from "@/components/ui";
import { SettingsPage } from "@/components/settings/SettingsPage";
import {
  RangeFilter,
  RETRIEVAL_WINDOWS,
  rangeParams,
  type RangeValue,
} from "@/components/audit/RangeFilter";
import { OverviewTab } from "@/components/audit/OverviewTab";
import { AiActivityTab } from "@/components/audit/AiActivityTab";
import { SecurityTab } from "@/components/audit/SecurityTab";
import { JobsTab } from "@/components/audit/JobsTab";
import { FailuresTab } from "@/components/audit/FailuresTab";
import { ChangesTab } from "@/components/audit/ChangesTab";
import { UsageTab } from "@/components/audit/UsageTab";
import { RetrievalTab } from "@/components/audit/retrieval/RetrievalTab";
import type { RetrievalWindow } from "@/api/retrieval";

export type AuditTab =
  | "overview"
  | "ai"
  | "usage"
  | "security"
  | "jobs"
  | "failures"
  | "changes"
  | "retrieval";

// Exported for the tab-param tests (the repo-wide ?tab= pattern).
export const AUDIT_TABS: readonly AuditTab[] = [
  "overview",
  "ai",
  "usage",
  "security",
  "jobs",
  "failures",
  "changes",
  "retrieval",
];

export function parseAuditTab(raw: string | null): AuditTab {
  return (AUDIT_TABS as readonly string[]).includes(raw ?? "")
    ? (raw as AuditTab)
    : "overview";
}

export function parseAuditWindow(
  raw: string | null,
): Exclude<RangeValue["window"], "custom" | ""> {
  if (raw === "7d" || raw === "30d" || raw === "90d") return raw;
  return "24h";
}

/** The audit & monitoring surface (plans 151-152): overview metrics, the
 * AI ledger, the security trail, jobs & runs, the data-change journal and
 * the read-only retrieval observation tab (plan 51 Q2b) — tabs URL-synced
 * via `?tab=`, the retrieval sections via `?section=` and `?detail=`. */
export function Audit() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const tabFromUrl = searchParams.get("tab");
  const activeTab = parseAuditTab(tabFromUrl);
  const tabsRef = useRef<HTMLDivElement | null>(null);
  const [range, setRange] = useState<RangeValue>({
    window: parseAuditWindow(searchParams.get("window")),
    from: "",
    to: "",
  });

  // 90d is a retrieval-only preset and retrieval has no custom range; a
  // tab that cannot express the stored window falls back to 24h without
  // discarding the retrieval preference.
  const effectiveWindow =
    activeTab === "retrieval" && (range.window === "custom" || range.window === "")
      ? "24h"
      : activeTab !== "retrieval" && range.window === "90d"
        ? "24h"
        : range.window;
  const effectiveRange: RangeValue =
    effectiveWindow === range.window ? range : { ...range, window: effectiveWindow };

  useEffect(() => {
    const expectedTab = activeTab === "overview" ? null : activeTab;
    const expectedWindow =
      effectiveWindow !== "24h" &&
      effectiveWindow !== "custom" &&
      effectiveWindow !== "" &&
      activeTab !== "ai"
        ? effectiveWindow
        : null;
    if (tabFromUrl === expectedTab && searchParams.get("window") === expectedWindow) return;
    const next = new URLSearchParams(searchParams);
    if (expectedTab) next.set("tab", expectedTab);
    else next.delete("tab");
    if (expectedWindow) next.set("window", expectedWindow);
    else next.delete("window");
    setSearchParams(next, { replace: true });
  }, [tabFromUrl, activeTab, effectiveWindow, searchParams, setSearchParams]);

  const setActive = (tab: AuditTab) => {
    const next = new URLSearchParams(searchParams);
    if (tab === "overview") next.delete("tab");
    else next.set("tab", tab);
    next.delete("detail");
    setSearchParams(next, { replace: true });
  };

  // The eight-tab strip overflows a phone width; keep the selected tab in
  // view when a deep link lands on a tab that starts off-screen. Scroll the
  // strip itself — `scrollIntoView` would also move ancestor containers.
  useEffect(() => {
    const container = tabsRef.current;
    const selected = container?.querySelector<HTMLElement>(
      '[role="tab"][aria-selected="true"]',
    );
    if (!container || !selected) return;
    const view = container.getBoundingClientRect();
    const tab = selected.getBoundingClientRect();
    if (tab.left >= view.left && tab.right <= view.right) return;
    container.scrollLeft +=
      tab.left - view.left - (view.width - tab.width) / 2;
  }, [activeTab]);

  return (
    <SettingsPage
      icon={Activity}
      title={t("settingsNav.audit.label")}
      description={t("settingsNav.audit.description")}
    >
      <section id="s-overview" className="scroll-mt-4">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div ref={tabsRef} className="min-w-0 max-w-full overflow-x-auto">
            <SegmentedTabs
              ariaLabel={t("audit.tabsAria")}
              className="min-w-max max-sm:[&>button]:min-h-9"
              items={AUDIT_TABS.map((tab) => ({
                value: tab,
                label: t(`audit.tab.${tab}`),
              }))}
              value={activeTab}
              onValueChange={(next) => setActive(next as AuditTab)}
            />
          </div>
          {(activeTab === "overview" ||
            activeTab === "security" ||
            activeTab === "failures" ||
            activeTab === "retrieval") && (
            <RangeFilter
              value={effectiveRange}
              onChange={setRange}
              windows={
                activeTab === "retrieval" ? RETRIEVAL_WINDOWS : undefined
              }
              allowCustom={activeTab !== "retrieval"}
              testId="audit-page-range"
            />
          )}
        </div>

        {activeTab === "overview" && (
          <OverviewTab range={rangeParams(effectiveRange)} />
        )}
        {activeTab === "ai" && <AiActivityTab />}
        {activeTab === "usage" && <UsageTab range={rangeParams(effectiveRange)} />}
        {activeTab === "security" && (
          <SecurityTab range={rangeParams(effectiveRange)} />
        )}
        {activeTab === "jobs" && <JobsTab />}
        {activeTab === "failures" && <FailuresTab range={effectiveRange} />}
        {activeTab === "changes" && <ChangesTab />}
        {activeTab === "retrieval" && (
          <RetrievalTab
            window={
              (effectiveRange.window === "custom" || effectiveRange.window === ""
                ? "24h"
                : effectiveRange.window) as RetrievalWindow
            }
          />
        )}
      </section>
    </SettingsPage>
  );
}
