import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  fetchRetrievalQueryHealth,
  type RetrievalQueryHealth,
  type RetrievalQueryHealthResponse,
  type RetrievalWindow,
} from "@/api/retrieval";
import { apiDetail } from "@/api/client";
import { Badge, PanelModal } from "@/components/ui";
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
  TOOLS_RETRIEVAL_URL,
} from "@/components/audit/retrieval/retrievalHelpers";

export function RetrievalQueryHealthSection({
  window,
  detailId,
  onOpenDetail,
  onCloseDetail,
}: {
  window: RetrievalWindow;
  detailId: string | null;
  onOpenDetail: (id: string) => void;
  onCloseDetail: () => void;
}) {
  const { t } = useTranslation();
  const [data, setData] = useState<RetrievalQueryHealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    setLoading(true);
    fetchRetrievalQueryHealth({ window })
      .then((loaded) => {
        if (!live) return;
        setData(loaded);
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

  const health = data?.query_health ?? null;
  const selectedReason =
    health && detailId && detailId in health.degraded_reasons ? detailId : null;

  if (loading) return <RetrievalLoading />;
  if (error) return <RetrievalError message={error} />;

  return (
    <div className="space-y-3" data-testid="retrieval-query-health">
      <RetrievalSectionHeader
        title={t("audit.retrieval.queryHealth.title")}
        hint={t("audit.retrieval.queryHealth.hint")}
        actions={
          <Link
            to={TOOLS_RETRIEVAL_URL}
            className="inline-flex items-center py-1 text-xs font-semibold text-[var(--as-primary)] hover:underline"
          >
            {t("audit.retrieval.openTools")} →
          </Link>
        }
      />

      {!data || data.state === "empty" || !health ? (
        <div data-testid="retrieval-query-empty">
          <StateNote>
            {data?.reason === "no_space_selected"
              ? t("audit.retrieval.queryHealth.noSpace")
              : t("audit.retrieval.queryHealth.empty")}
          </StateNote>
        </div>
      ) : data.state === "not_sampled" ? (
        <div data-testid="retrieval-query-not-sampled">
          <StateNote>{t("audit.retrieval.queryHealth.neverSampled")}</StateNote>
        </div>
      ) : (
        <QueryHealthBody
          health={health}
          response={data}
          onOpenReason={onOpenDetail}
        />
      )}

      <QueryReasonDrawer
        reason={selectedReason}
        health={health}
        onClose={onCloseDetail}
      />
    </div>
  );
}

function QueryHealthBody({
  health,
  response,
  onOpenReason,
}: {
  health: RetrievalQueryHealth;
  response: RetrievalQueryHealthResponse;
  onOpenReason: (id: string) => void;
}) {
  const { t } = useTranslation();
  const degradedReasons = Object.entries(health.degraded_reasons).sort(
    (a, b) => b[1] - a[1],
  );
  const viewHits = Object.entries(health.per_view_hits).sort((a, b) => b[1] - a[1]);
  const tiles: StatTile[] = [
    {
      label: t("audit.retrieval.queryHealth.p50"),
      value: formatMs(health.p50_ms),
      hint: t("audit.retrieval.queryHealth.latencyHint", {
        count: formatNumber(health.query_count),
      }),
    },
    {
      label: t("audit.retrieval.queryHealth.p95"),
      value: formatMs(health.p95_ms),
      hint:
        response.latency_percentiles === "histogram_bucket_upper_bound"
          ? t("audit.retrieval.queryHealth.histogram")
          : t("retrieval.state.not_sampled"),
    },
    {
      label: t("audit.retrieval.queryHealth.candidates"),
      value:
        response.candidates_avg == null
          ? t("retrieval.state.not_sampled")
          : response.candidates_avg.toFixed(2),
      hint:
        response.candidate_percentiles === "unavailable"
          ? t("audit.retrieval.queryHealth.candidateUnavailable")
          : t("audit.retrieval.queryHealth.candidateHint"),
    },
    {
      label: t("audit.retrieval.queryHealth.zeroResult"),
      value: formatRate(health.zero_result_rate),
      hint: t("audit.retrieval.queryHealth.zeroResultHint"),
    },
    {
      label: t("audit.retrieval.queryHealth.degraded"),
      value: formatRate(health.degraded_rate),
      hint: t("audit.retrieval.queryHealth.degradedHint"),
    },
    {
      label: t("audit.retrieval.queryHealth.annRecall"),
      value: health.ann_recall == null ? t("retrieval.state.not_sampled") : formatRate(health.ann_recall),
      hint:
        health.ann_recall_k == null
          ? t("audit.retrieval.queryHealth.annHint")
          : t("audit.retrieval.queryHealth.annSampled", {
              k: health.ann_recall_k,
              probes: health.probe_size ?? 0,
            }),
    },
  ];
  return (
    <div className="space-y-3" data-testid="retrieval-query-ok">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-[var(--as-muted-fg)]">
          {t("audit.retrieval.queryHealth.sampleSize", {
            count: formatNumber(health.sample_size),
          })}
        </span>
        {health.sampled && (
          <Badge variant="success">{t("audit.retrieval.queryHealth.sampled")}</Badge>
        )}
      </div>
      <StatTiles tiles={tiles} layout="auto" testId="retrieval-query-tiles" />

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4">
          <h3 className="mb-2 text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
            {t("audit.retrieval.queryHealth.perView")}
          </h3>
          {viewHits.length === 0 ? (
            <p className="text-xs text-[var(--as-muted-fg)]">
              {t("audit.retrieval.queryHealth.noViewHits")}
            </p>
          ) : (
            <ul className="space-y-1" data-testid="retrieval-query-views">
              {viewHits.map(([view, count]) => (
                <li
                  key={view}
                  className="flex items-center justify-between gap-2 text-xs"
                >
                  <span>{t(`retrieval.view.${view}`, { defaultValue: view })}</span>
                  <span className="tabular-nums text-[var(--as-muted-fg)]">
                    {formatNumber(count)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4">
          <h3 className="mb-2 text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
            {t("audit.retrieval.queryHealth.degradedReasons")}
          </h3>
          {degradedReasons.length === 0 ? (
            <p className="text-xs text-[var(--as-muted-fg)]">
              {t("audit.retrieval.queryHealth.noDegraded")}
            </p>
          ) : (
            <ul className="space-y-1" data-testid="retrieval-query-reasons">
              {degradedReasons.map(([reason, count]) => (
                <li key={reason}>
                  <button
                    type="button"
                    className="flex w-full items-center justify-between gap-2 rounded px-1 py-0.5 text-left text-xs text-[var(--as-fg)] hover:bg-[var(--as-muted)] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--as-accent)]"
                    onClick={() => onOpenReason(reason)}
                    data-testid={`retrieval-query-reason-${reason}`}
                  >
                    <span>
                      {t(`audit.retrieval.reason.${reason}`, {
                        defaultValue: reason,
                      })}
                    </span>
                    <span className="tabular-nums text-[var(--as-muted-fg)]">
                      {formatNumber(count)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function QueryReasonDrawer({
  reason,
  health,
  onClose,
}: {
  reason: string | null;
  health: RetrievalQueryHealth | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const count = reason ? health?.degraded_reasons[reason] ?? 0 : 0;
  return (
    <PanelModal
      open={reason !== null}
      onOpenChange={(open) => !open && onClose()}
      title={t("audit.retrieval.queryHealth.reasonDrawerTitle")}
      data-testid="retrieval-query-drawer"
    >
      {reason && health && (
        <div className="space-y-3 text-sm">
          <p className="font-medium text-[var(--as-fg)]">
            {t(`audit.retrieval.reason.${reason}`, { defaultValue: reason })}
          </p>
          <dl className="space-y-1 text-xs">
            <div className="flex justify-between gap-2">
              <dt className="text-[var(--as-muted-fg)]">
                {t("audit.retrieval.queryHealth.reasonCode")}
              </dt>
              <dd className="font-mono text-[11px]">{reason}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-[var(--as-muted-fg)]">
                {t("audit.retrieval.queryHealth.count")}
              </dt>
              <dd className="tabular-nums">{formatNumber(count)}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-[var(--as-muted-fg)]">
                {t("audit.retrieval.queryHealth.share")}
              </dt>
              <dd className="tabular-nums">
                {formatRate(
                  health.query_count > 0 ? count / health.query_count : null,
                )}
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-[var(--as-muted-fg)]">
                {t("audit.retrieval.queryHealth.window")}
              </dt>
              <dd className="text-right text-[11px]">
                {health.window_start} → {health.window_end}
              </dd>
            </div>
          </dl>
          <p className="text-[11px] text-[var(--as-muted-fg)]">
            {t("audit.retrieval.queryHealth.structuredOnly")}
          </p>
        </div>
      )}
    </PanelModal>
  );
}
