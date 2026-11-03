import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  fetchRetrievalOverview,
  fetchRetrievalSpaces,
  type RetrievalOverview,
  type RetrievalSpacesResponse,
  type RetrievalWindow,
} from "@/api/retrieval";
import { apiDetail } from "@/api/client";
import { Badge } from "@/components/ui";
import { StatTiles, type StatTile } from "@/components/stats/StatTiles";
import {
  RetrievalError,
  RetrievalLoading,
  RetrievalSectionHeader,
  StateNote,
} from "@/components/audit/retrieval/RetrievalCommon";
import {
  formatMs,
  formatNumber,
  formatRate,
  shortId,
  TOOLS_RETRIEVAL_URL,
  when,
} from "@/components/audit/retrieval/retrievalHelpers";

export function RetrievalOverviewSection({ window }: { window: RetrievalWindow }) {
  const { t } = useTranslation();
  const [overview, setOverview] = useState<RetrievalOverview | null>(null);
  const [spaces, setSpaces] = useState<RetrievalSpacesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    setLoading(true);
    Promise.all([fetchRetrievalOverview(window), fetchRetrievalSpaces()])
      .then(([loadedOverview, loadedSpaces]) => {
        if (!live) return;
        setOverview(loadedOverview);
        setSpaces(loadedSpaces);
        setError("");
      })
      .catch((err) => {
        if (live) setError(apiDetail(err));
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [window]);

  if (loading) return <RetrievalLoading />;
  if (error) return <RetrievalError message={error} />;

  if (!overview || overview.state === "empty") {
    return (
      <div
        className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-6"
        data-testid="retrieval-overview-empty"
      >
        <StateNote>{t("audit.retrieval.overview.empty")}</StateNote>
        <Link
          to={TOOLS_RETRIEVAL_URL}
          className="mt-3 inline-flex text-xs font-semibold text-[var(--as-primary)] hover:underline"
        >
          {t("audit.retrieval.openTools")} →
        </Link>
      </div>
    );
  }

  const activeSpace =
    spaces?.spaces.find((space) => space.status === "active") ?? null;
  const cold = overview.coverage.state === "never_reconciled";
  const noQueries = overview.queries.count === 0;
  const degraded = (overview.queries.degraded_rate ?? 0) > 0;
  const backendUnavailable = !overview.backend.semantic_available;

  const tiles: StatTile[] = [
    {
      label: t("audit.retrieval.metric.spaces"),
      value: overview.spaces.total.toLocaleString(),
      hint: t("audit.retrieval.overview.spacesHint", {
        active: overview.spaces.active,
        building: overview.spaces.building,
        retired: overview.spaces.retired,
      }),
    },
    {
      label: t("audit.retrieval.metric.backend"),
      value: overview.backend.label,
      hint: t(`audit.retrieval.backend.${overview.backend.name}`, {
        defaultValue: overview.backend.dialect,
      }),
      title: overview.backend.name,
    },
    {
      label: t("audit.retrieval.metric.model"),
      value: activeSpace ? `${activeSpace.model} · ${activeSpace.dim}` : "—",
      hint: activeSpace?.name ?? t("audit.retrieval.overview.noActiveSpace"),
    },
    {
      label: t("audit.retrieval.metric.coverage"),
      value: cold ? t("retrieval.state.never_reconciled") : formatRate(overview.coverage.coverage),
      hint: cold
        ? t("audit.retrieval.overview.coldHint")
        : t("audit.retrieval.overview.coverageHint", {
            stale: overview.coverage.stale ?? 0,
            failed: overview.coverage.failed ?? 0,
          }),
      title: cold ? undefined : t("audit.retrieval.overview.docsRecords", {
        docs: formatNumber(overview.documents),
        records: formatNumber(overview.records),
      }),
    },
    {
      label: t("audit.retrieval.metric.queryLatency"),
      value: noQueries
        ? t("retrieval.state.not_sampled")
        : `${formatMs(overview.queries.p50_ms)} / ${formatMs(overview.queries.p95_ms)}`,
      hint: noQueries
        ? t("audit.retrieval.overview.noQueriesHint")
        : t("audit.retrieval.overview.latencyHint", {
            count: overview.queries.count,
          }),
    },
    {
      label: t("audit.retrieval.metric.searchQuality"),
      value: noQueries
        ? t("retrieval.state.not_sampled")
        : t("audit.retrieval.overview.qualityValue", {
            zero: formatRate(overview.queries.zero_result_rate),
            degraded: formatRate(overview.queries.degraded_rate),
          }),
      hint: noQueries
        ? t("audit.retrieval.overview.noQueriesHint")
        : t("audit.retrieval.overview.qualityHint"),
    },
    {
      label: t("audit.retrieval.metric.embedUsage"),
      value: t("audit.retrieval.overview.embedValue", {
        calls: formatNumber(overview.embed.calls),
        tokens: formatNumber(overview.embed.tokens_in + overview.embed.tokens_out),
      }),
      hint: t("audit.retrieval.overview.embedHint", {
        errors: overview.embed.errors,
      }),
    },
    {
      label: t("audit.retrieval.metric.lastReindex"),
      value: when(overview.runs.last_reindex_at),
      hint: overview.runs.last_status
        ? t(`retrieval.status.${overview.runs.last_status}`, {
            defaultValue: overview.runs.last_status,
          })
        : t("audit.retrieval.overview.noReindex"),
    },
    {
      label: t("audit.retrieval.metric.changes"),
      value: formatNumber(overview.changes.count),
      hint:
        overview.changes.state === "empty"
          ? t("audit.retrieval.overview.noChanges")
          : t("audit.retrieval.overview.changesHint"),
    },
  ];

  return (
    <div className="space-y-4" data-testid="retrieval-overview">
      <RetrievalSectionHeader
        title={t("audit.retrieval.overview.title")}
        hint={t("audit.retrieval.overview.hint")}
        actions={
          <Link
            to={TOOLS_RETRIEVAL_URL}
            className="text-xs font-semibold text-[var(--as-primary)] hover:underline"
            data-testid="retrieval-overview-tools-link"
          >
            {t("audit.retrieval.openTools")} →
          </Link>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        {cold && (
          <Badge variant="secondary" data-testid="retrieval-overview-cold">
            {t("audit.retrieval.overview.cold")}
          </Badge>
        )}
        {noQueries && (
          <Badge variant="secondary" data-testid="retrieval-overview-no-queries">
            {t("audit.retrieval.overview.noQueries")}
          </Badge>
        )}
        {degraded && (
          <Badge variant="warning" data-testid="retrieval-overview-degraded">
            {t("audit.retrieval.overview.degraded", {
              rate: formatRate(overview.queries.degraded_rate),
            })}
          </Badge>
        )}
        {backendUnavailable && (
          <Badge variant="warning" data-testid="retrieval-overview-linear">
            {t("audit.retrieval.overview.linearFallback")}
          </Badge>
        )}
        {overview.runs.unattributed > 0 && (
          <Badge variant="secondary" data-testid="retrieval-overview-unattributed">
            {t("audit.retrieval.runs.unattributed", {
              count: overview.runs.unattributed,
            })}
          </Badge>
        )}
      </div>

      <StatTiles tiles={tiles} layout="auto" testId="retrieval-overview-tiles" />

      <div className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4">
        <RetrievalSectionHeader
          title={t("audit.retrieval.overview.recentChanges")}
          hint={t("audit.retrieval.overview.recentChangesHint")}
        />
        {overview.changes.recent.length === 0 ? (
          <p className="mt-2 text-xs text-[var(--as-muted-fg)]">
            {t("audit.retrieval.changes.empty")}
          </p>
        ) : (
          <ul className="mt-2 divide-y divide-[var(--as-border)]">
            {overview.changes.recent.map((change, index) => (
              <li
                key={`${change.action}-${change.created_at}-${index}`}
                className="flex flex-wrap items-center gap-2 py-1.5 text-xs"
                data-testid="retrieval-overview-change"
              >
                <span className="font-mono font-medium text-[var(--as-fg)]">
                  {change.action}
                </span>
                <span className="text-[var(--as-muted-fg)]">
                  {shortId(change.actor)}
                </span>
                <span className="text-[var(--as-muted-fg)]">
                  {change.resource || "—"}
                </span>
                <span className="ml-auto text-[var(--as-muted-fg)]">
                  {when(change.created_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
