import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { RunSummary } from "@/api/sources";

/**
 * The run drawer's summary strip (plan 003): what the run did — the
 * configured detail session, browser launches per profile, pages loaded
 * by kind, the budget split, and the walled-skip count with an
 * expandable id list. Rendered only when report.run_summary exists;
 * runs and bundles without one degrade silently.
 */

export function RunSummaryStrip({ summary }: { summary: RunSummary }) {
  const { t } = useTranslation();
  const [showWalled, setShowWalled] = useState(false);
  const launches = summary.launches ?? {};
  const navigations = summary.navigations ?? {};
  const budget = summary.budget ?? {};
  const walled = summary.walled_skips ?? [];
  const limit = Math.max(0, Number(budget.limit_s ?? 0));
  const searchUsed = Math.max(0, Number(budget.search_used_s ?? 0));
  const detailUsed = Math.max(0, Number(budget.detail_used_s ?? 0));
  const searchPct = limit > 0 ? Math.min(100, (searchUsed / limit) * 100) : 0;
  const detailPct =
    limit > 0 ? Math.min(100 - searchPct, (detailUsed / limit) * 100) : 0;
  const usedTotal = Math.round((searchUsed + detailUsed) * 10) / 10;
  const modeLabel =
    summary.mode === "authenticated"
      ? t("sourceDetail.runSummaryModeAuthenticated")
      : t("sourceDetail.runSummaryModeGuest");

  return (
    <div
      className="space-y-2 rounded-[var(--as-radius-sm)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
      data-testid="run-summary"
    >
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-medium">{t("sourceDetail.runSummaryTitle")}</span>
        <span
          className="rounded-full border border-[var(--as-border)] px-2 py-0.5"
          data-testid="run-summary-mode"
        >
          {t("sourceDetail.runSummaryMode")}: {modeLabel}
        </span>
      </div>
      <p
        className="text-xs text-[var(--as-muted-fg)]"
        data-testid="run-summary-launches"
      >
        {t("sourceDetail.runSummaryLaunches", {
          guest: launches.guest ?? 0,
          authenticated: launches.authenticated ?? 0,
        })}
      </p>
      <p
        className="text-xs text-[var(--as-muted-fg)]"
        data-testid="run-summary-navigations"
      >
        {t("sourceDetail.runSummaryNavigations", {
          search: navigations.search_pages ?? 0,
          details: navigations.detail_pages ?? 0,
        })}
      </p>
      <div className="space-y-1">
        <div
          className="flex h-2 w-full overflow-hidden rounded-full border border-[var(--as-border)] bg-[var(--as-muted)]"
          data-testid="run-summary-budget-bar"
          role="img"
          aria-label={t("sourceDetail.runSummaryBudget", {
            used: usedTotal,
            limit,
            search: searchUsed,
            details: detailUsed,
          })}
        >
          <div
            className="h-full bg-[var(--as-info)]"
            data-testid="run-summary-budget-search"
            style={{ width: `${searchPct}%` }}
          />
          <div
            className="h-full bg-[var(--as-warning)]"
            data-testid="run-summary-budget-detail"
            style={{ width: `${detailPct}%` }}
          />
        </div>
        <p
          className="text-xs text-[var(--as-muted-fg)]"
          data-testid="run-summary-budget-label"
        >
          {t("sourceDetail.runSummaryBudget", {
            used: usedTotal,
            limit,
            search: searchUsed,
            details: detailUsed,
          })}
        </p>
      </div>
      {walled.length > 0 ? (
        <div className="space-y-1">
          <button
            type="button"
            className="text-xs text-[var(--as-fg)] underline"
            data-testid="run-summary-walled-toggle"
            onClick={() => setShowWalled((open) => !open)}
          >
            {t("sourceDetail.runSummaryWalled", { count: walled.length })} ·{" "}
            {showWalled
              ? t("sourceDetail.runSummaryWalledHide")
              : t("sourceDetail.runSummaryWalledShow")}
          </button>
          {showWalled ? (
            <p
              className="break-words rounded-[var(--as-radius-sm)] border border-[var(--as-border)] bg-[var(--as-muted)] p-2 font-mono text-xs"
              data-testid="run-summary-walled-ids"
            >
              {walled.join(", ")}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
