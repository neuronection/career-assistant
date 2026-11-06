import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { PostingSource } from "@/api/sources";
import { fetchSystemSchedules } from "@/api/scheduler";

/**
 * The merged-query management view (plans 130/133/134): every rotating
 * role group with WHEN it will be searched (next-run estimates from the
 * cadence, batch size and rotation cursor), the grouping mode and compute
 * time, the location, the effective arguments and the coverage arithmetic
 * — shared by the row dialog and the source management page.
 */

function argsSummary(source: PostingSource): string[] {
  const parts: string[] = [
    `${source.query_batch_size || 1} quer${(source.query_batch_size || 1) === 1 ? "y" : "ies"} per sync`,
  ];
  let options: Record<string, unknown> = {};
  try {
    options = JSON.parse(String(source.config.options ?? "{}")) as Record<string, unknown>;
  } catch {
    options = {};
  }
  const pick = (key: string, label: string) => {
    const value = options[key];
    if (value !== undefined && value !== null && value !== "") parts.push(`${label} ${value}`);
  };
  pick("max_pages", "pages");
  pick("query_interval_seconds", "interval");
  pick("nav_delay_seconds", "nav pause");
  pick("budget_seconds", "budget");
  pick("fetch_details", "details");
  return parts;
}

export function QueryPlanPanel({ source }: { source: PostingSource }) {
  const { t } = useTranslation();
  const plan = source.query_info;
  const groups = plan?.groups ?? [];
  const current = plan?.rotation_index ?? 0;
  const batch = source.query_batch_size || 1;
  const [cadenceMinutes, setCadenceMinutes] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchSystemSchedules()
      .then((rows) => {
        const row = rows.find((entry) => entry.kind === "system_source_sync");
        const params = (row?.trigger?.params ?? {}) as { every_minutes?: number };
        if (!cancelled) setCadenceMinutes(params.every_minutes ?? null);
      })
      .catch(() => setCadenceMinutes(null));
    return () => {
      cancelled = true;
    };
  }, []);

  const timing = useMemo(() => {
    const n = groups.length;
    const syncsAway = (index: number): number => {
      if (n === 0 || index === current % n) return 0;
      return Math.ceil((((index - current) % n) + n) % n / batch);
    };
    const fmt = (syncs: number): string => {
      if (syncs === 0) return t("toolsSettings.connectors.sources.planNext");
      if (cadenceMinutes) {
        return t("toolsSettings.connectors.sources.planNextAt", {
          time: new Date(Date.now() + syncs * cadenceMinutes * 60_000).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          }),
        });
      }
      return t("toolsSettings.connectors.sources.planInSynces", { count: syncs });
    };
    const fullPassSyncs = Math.ceil(n / batch);
    const fullPassHours = cadenceMinutes ? (fullPassSyncs * cadenceMinutes) / 60 : null;
    return { syncsAway, fmt, fullPassSyncs, fullPassHours };
  }, [groups.length, current, batch, cadenceMinutes, t]);

  return (
    <div className="space-y-4" data-testid="query-plan">
      <p className="text-xs text-[var(--as-muted-fg)]">
        {t("toolsSettings.connectors.sources.planExplainer")}
      </p>
      <p className="text-xs text-[var(--as-muted-fg)]">
        {t("toolsSettings.connectors.sources.planMerged", {
          count: plan?.radar_ids?.length ?? 0,
          grouping: plan?.curated
            ? t("toolsSettings.connectors.sources.planCurated")
            : t("toolsSettings.connectors.sources.planDeterministic"),
        })}
        {plan?.computed_at
          ? ` · ${t("toolsSettings.connectors.sources.planComputed", {
              time: new Date(plan.computed_at).toLocaleString(),
            })}`
          : ""}
      </p>

      {groups.length === 0 ? (
        <p className="text-sm text-[var(--as-muted-fg)]" data-testid="query-plan-empty">
          {source.query_mode === "radar"
            ? t("toolsSettings.connectors.sources.planPending")
            : t("toolsSettings.connectors.sources.planEmpty")}
        </p>
      ) : (
        <>
          <ol className="space-y-3">
            {groups.map((group, index) => {
              const provenanceChips = group.terms
                .map((term) => ({
                  term,
                  count: plan?.provenance?.[term]?.length ?? 0,
                }))
                .filter((chip) => chip.count > 0);
              return (
              <li
                key={`${group.keywords}-${index}`}
                className="rounded-[var(--as-radius-sm)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
                data-testid={`query-plan-group-${index}`}
                data-current={index === current % groups.length ? "true" : "false"}
              >
                <div className="flex items-start gap-2">
                  <span aria-hidden className="mt-1">
                    {index === current % groups.length ? "●" : "○"}
                  </span>
                  <div className="min-w-0 space-y-1">
                    <p className="break-words text-sm font-medium text-[var(--as-fg)]">
                      {group.keywords}
                    </p>
                    <p className="text-xs text-[var(--as-muted-fg)]">
                      {t("toolsSettings.connectors.sources.planTerms", {
                        terms: group.terms.join(", "),
                      })}
                    </p>
                    {provenanceChips.length > 0 ? (
                      <p
                        className="flex flex-wrap gap-1"
                        data-testid={`query-plan-provenance-${index}`}
                      >
                        {provenanceChips.map((chip) => (
                          <span
                            key={chip.term}
                            className="rounded-full bg-[var(--as-muted)] px-1.5 py-0.5 text-[10px] text-[var(--as-muted-fg)]"
                          >
                            {chip.term} ·{" "}
                            {t("toolsSettings.connectors.sources.planSources", {
                              count: chip.count,
                            })}
                          </span>
                        ))}
                      </p>
                    ) : null}
                  </div>
                  <span className="ml-auto shrink-0 text-xs text-[var(--as-muted-fg)]">
                    {timing.fmt(timing.syncsAway(index))}
                  </span>
                </div>
              </li>
              );
            })}
          </ol>
          <p className="text-xs text-[var(--as-muted-fg)]" data-testid="query-plan-coverage">
            {t("toolsSettings.connectors.sources.planFullPass", {
              hours:
                timing.fullPassHours !== null
                  ? timing.fullPassHours < 10
                    ? timing.fullPassHours.toFixed(1)
                    : Math.round(timing.fullPassHours)
                  : "?",
              groups: groups.length,
              batch,
              cadence: cadenceMinutes ?? "?",
            })}
          </p>
          {timing.fullPassHours !== null && timing.fullPassHours > 24 ? (
            <p className="text-xs text-[var(--as-warning)]" data-testid="query-plan-slow">
              {t("toolsSettings.connectors.sources.planSlowHint")}
            </p>
          ) : null}
        </>
      )}

      <div className="space-y-1">
        <p className="text-xs font-medium text-[var(--as-fg)]">
          {t("toolsSettings.connectors.sources.planLocation")}
        </p>
        <p className="text-xs text-[var(--as-muted-fg)]">
          {plan?.location || t("toolsSettings.connectors.sources.planNoLocation")}
        </p>
      </div>

      <div className="space-y-1">
        <p className="text-xs font-medium text-[var(--as-fg)]">
          {t("toolsSettings.connectors.sources.planArgs")}
        </p>
        <p className="text-xs text-[var(--as-muted-fg)]">{argsSummary(source).join(" · ")}</p>
      </div>

      <div className="space-y-1">
        <p className="text-xs font-medium text-[var(--as-fg)]">
          {t("toolsSettings.connectors.sources.planCadence")}
        </p>
        <p className="text-xs text-[var(--as-muted-fg)]">
          {cadenceMinutes
            ? t("toolsSettings.connectors.sources.planCadenceValue", {
                minutes: cadenceMinutes,
                jitter: 30,
              })
            : t("toolsSettings.connectors.sources.planCadenceUnknown")}
        </p>
      </div>
    </div>
  );
}
