import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { PostingSource } from "@/api/sources";
import { fetchSystemSchedules } from "@/api/scheduler";

/**
 * The merged-query management view (plans 130/133/134): every rotating
 * role group with the next-search marker, the grouping mode and compute
 * time, the location, the effective arguments and the cadence — shared
 * by the row dialog and the source management page.
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
  const [cadence, setCadence] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchSystemSchedules()
      .then((rows) => {
        const row = rows.find((entry) => entry.kind === "system_source_sync");
        const params = (row?.trigger?.params ?? {}) as {
          every_minutes?: number;
          jitter_minutes?: number;
        };
        if (!cancelled && params.every_minutes) {
          setCadence(
            t("toolsSettings.connectors.sources.planCadenceValue", {
              minutes: params.every_minutes,
              jitter: params.jitter_minutes ?? 0,
            }),
          );
        }
      })
      .catch(() => setCadence(""));
    return () => {
      cancelled = true;
    };
  }, [t]);

  return (
    <div className="space-y-4" data-testid="query-plan">
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
        <ol className="space-y-3">
          {groups.map((group, index) => (
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
                </div>
                {index === current % groups.length ? (
                  <span className="ml-auto shrink-0 text-xs text-[var(--as-muted-fg)]">
                    {t("toolsSettings.connectors.sources.planNext")}
                  </span>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
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
          {cadence || t("toolsSettings.connectors.sources.planCadenceUnknown")}
        </p>
      </div>
    </div>
  );
}
