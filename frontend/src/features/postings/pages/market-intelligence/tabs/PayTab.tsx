import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { fetchSalaryBenchmarks, type SalaryBenchmarks } from "@/api/stats";
import { formatMoney } from "@/lib/money";
import { SalaryCard } from "../cards";
import { dashboardParams } from "../../marketStatsParams";
import type { TabProps } from "./shared";

export function PayTab({ data, view, loading, compact, refresh, onDrill }: TabProps) {
  const { t, i18n } = useTranslation();
  const [benchmarks, setBenchmarks] = useState<SalaryBenchmarks | null>(null);
  const [benchError, setBenchError] = useState(false);
  const key = `${view.window}|${view.from}|${view.to}|${view.basis}|${JSON.stringify(view.segments)}`;

  useEffect(() => {
    let alive = true;
    setBenchError(false);
    const params = dashboardParams(view);
    delete params.cards;
    delete params.dimension;
    delete params.split;
    params.status_basis = view.basis;
    void fetchSalaryBenchmarks(params)
      .then((result) => {
        if (alive) setBenchmarks(result);
      })
      .catch(() => {
        if (alive) {
          setBenchmarks(null);
          setBenchError(true);
        }
      });
    return () => {
      alive = false;
    };
  }, [key, view.basis, view.from, view.to, view.window]);

  return (
    <div className="space-y-4">
      <SalaryCard
        salary={data.salary}
        loading={loading}
        error={data.errors.salary ?? null}
        onRetry={refresh}
        onBucket={(floor) => onDrill(`salary_min=${Math.round(floor)}`)}
        compact={compact}
        windowName={view.window}
      />
      <section
        className="rounded-[var(--as-radius)] border border-[var(--as-border)] p-3"
        data-testid="salary-benchmarks"
      >
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold text-[var(--as-fg)]">
              {t("marketStats.benchmarks.title")}
            </h3>
            <p className="text-xs text-[var(--as-muted-fg)]">
              {t("marketStats.benchmarks.hint")}
            </p>
          </div>
          <span className="text-[10px] text-[var(--as-muted-fg)]">
            {t("marketStats.benchmarks.floor", { floor: benchmarks?.floor ?? 10 })} ·{" "}
            {t("marketStats.benchmarks.annual")}
          </span>
        </div>

        {benchError ? (
          <p className="mt-2 text-xs text-[var(--as-danger)]" role="alert">
            {t("marketStats.benchmarks.error")}
          </p>
        ) : benchmarks === null ? (
          <p className="mt-2 text-xs text-[var(--as-muted-fg)]">{t("common.loading")}</p>
        ) : benchmarks.cells.length === 0 ? (
          <p className="mt-2 text-xs text-[var(--as-muted-fg)]">
            {t("marketStats.benchmarks.empty")}
          </p>
        ) : (
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-[var(--as-muted-fg)]">
                <tr>
                  <th className="py-1 pr-2 font-medium">{t("marketStats.benchmarks.role")}</th>
                  <th className="py-1 pr-2 font-medium">{t("marketStats.benchmarks.country")}</th>
                  <th className="py-1 pr-2 font-medium">
                    {t("marketStats.benchmarks.seniority")}
                  </th>
                  <th className="py-1 pr-2 text-right font-medium">
                    {t("marketStats.benchmarks.n")}
                  </th>
                  <th className="py-1 pr-2 text-right font-medium">
                    {t("marketStats.benchmarks.p25")}
                  </th>
                  <th className="py-1 pr-2 text-right font-medium">
                    {t("marketStats.benchmarks.p50")}
                  </th>
                  <th className="py-1 text-right font-medium">
                    {t("marketStats.benchmarks.p75")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {benchmarks.cells.map((cell, index) => (
                  <tr
                    key={`${cell.scope}-${cell.job_code}-${cell.family_key}-${cell.country}-${cell.seniority}-${cell.currency}-${index}`}
                    className="border-t border-[var(--as-border)]"
                    data-testid={`salary-benchmark-${index}`}
                  >
                    <td className="py-1 pr-2 text-[var(--as-fg)]">
                      {cell.scope === "family" && cell.family_title
                        ? cell.family_title
                        : cell.job_title}
                      {cell.scope === "family" && (
                        <span className="ml-1 text-[var(--as-muted-fg)]">
                          ({t("marketStats.benchmarks.family")})
                        </span>
                      )}
                    </td>
                    <td className="py-1 pr-2 text-[var(--as-muted-fg)]">{cell.country}</td>
                    <td className="py-1 pr-2 text-[var(--as-muted-fg)]">
                      {t(`marketStats.value.${cell.seniority}`, {
                        defaultValue: cell.seniority.replace(/_/g, " "),
                      })}
                    </td>
                    <td className="py-1 pr-2 text-right tabular-nums">{cell.n}</td>
                    <td className="py-1 pr-2 text-right tabular-nums">
                      {cell.thin_sample ? "—" : formatMoney(cell.p25, cell.currency, i18n.language)}
                    </td>
                    <td className="py-1 pr-2 text-right tabular-nums">
                      {cell.thin_sample ? "—" : formatMoney(cell.p50, cell.currency, i18n.language)}
                    </td>
                    <td className="py-1 text-right tabular-nums">
                      {cell.thin_sample ? "—" : formatMoney(cell.p75, cell.currency, i18n.language)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {benchmarks && benchmarks.notes.length > 0 && (
          <ul className="mt-2 list-disc space-y-0.5 pl-5 text-[10px] text-[var(--as-muted-fg)]">
            {benchmarks.notes.map((note, index) => (
              <li key={note}>
                {t(`marketStats.benchmarks.notes.${benchmarks.note_codes[index] ?? "note"}`, {
                  defaultValue: note,
                })}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
