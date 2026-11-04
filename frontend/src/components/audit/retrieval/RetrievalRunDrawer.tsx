import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  fetchRetrievalRun,
  type RetrievalRunDetailResponse,
} from "@/api/retrieval";
import { apiDetail } from "@/api/client";
import { Badge, PanelModal, Spinner } from "@/components/ui";
import { GateBadge } from "@/components/audit/retrieval/RetrievalCommon";
import { RetrievalProgress } from "@/components/audit/retrieval/RetrievalProgress";
import {
  formatNumber,
  shortId,
  statusVariant,
  TOOLS_RETRIEVAL_URL,
  when,
} from "@/components/audit/retrieval/retrievalHelpers";

const FAILED_ID_DISPLAY_LIMIT = 100;

function MetaRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-xs">
      <dt className="text-[var(--as-muted-fg)]">{label}</dt>
      <dd className="min-w-0 break-words text-right font-medium text-[var(--as-fg)]">
        {children}
      </dd>
    </div>
  );
}

/** The Runs-section drawer: stage/progress/result counters, bounded
 * `failed_ids` with an explicit truncation marker, scope and heartbeat.
 * Audit never writes; cancel/retry deep-link to Tools → Retrieval. */
export function RetrievalRunDrawer({
  runId,
  onClose,
}: {
  runId: string | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [payload, setPayload] = useState<RetrievalRunDetailResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!runId) {
      setPayload(null);
      setError("");
      return;
    }
    let live = true;
    setLoading(true);
    fetchRetrievalRun(runId)
      .then((loaded) => {
        if (!live) return;
        setPayload(loaded);
        setError("");
      })
      .catch((err) => {
        if (live) {
          setPayload(null);
          setError(apiDetail(err));
        }
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [runId]);

  const run = payload?.detail.run ?? null;
  const result = payload?.detail.result ?? null;
  const failedIds = result?.failed_ids ?? [];
  const shownIds = failedIds.slice(0, FAILED_ID_DISPLAY_LIMIT);
  const truncated =
    !!result?.failed_ids_truncated || failedIds.length > FAILED_ID_DISPLAY_LIMIT;

  return (
    <PanelModal
      open={runId !== null}
      onOpenChange={(open) => !open && onClose()}
      title={
        run
          ? t("audit.retrieval.runs.drawerTitle", {
              type: t(`retrieval.runType.${run.job_type}`),
              id: shortId(run.run_id),
            })
          : t("audit.retrieval.runs.drawerTitleFallback")
      }
      size="lg"
      data-testid="retrieval-run-drawer"
    >
      {loading ? (
        <div className="py-8">
          <Spinner />
        </div>
      ) : error ? (
        <p className="text-sm text-rose-600" role="alert">
          {error}
        </p>
      ) : run ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={statusVariant(run.status)}>
              {t(`retrieval.status.${run.status}`)}
            </Badge>
            <span className="text-xs text-[var(--as-muted-fg)]">
              {t(`retrieval.runType.${run.job_type}`)}
            </span>
            <span className="font-mono text-[11px] text-[var(--as-muted-fg)]">
              {run.run_id}
            </span>
            {run.cancel_requested && (
              <Badge variant="warning">
                {t("audit.retrieval.runs.cancelRequested")}
              </Badge>
            )}
            {payload?.state === "degraded" && (
              <Badge variant="warning">
                {t("audit.retrieval.runs.resultUnreadable")}
              </Badge>
            )}
          </div>

          <dl className="space-y-1" data-testid="retrieval-run-meta">
            <MetaRow label={t("audit.retrieval.runs.space")}>
              <span className="font-mono text-[11px]">{shortId(run.space_id)}</span>
            </MetaRow>
            <MetaRow label={t("audit.retrieval.runs.stage")}>
              {run.stage ?? "—"}
            </MetaRow>
            <MetaRow label={t("audit.retrieval.runs.progress")}>
              {run.progress}%
            </MetaRow>
            <MetaRow label={t("audit.retrieval.runs.scope")}>
              {run.scope.kind ?? t("retrieval.kind.all")} ·{" "}
              {run.scope.view ?? t("retrieval.view.all")}
              {run.scope.since ? ` · ${run.scope.since}` : ""}
            </MetaRow>
            <MetaRow label={t("audit.retrieval.runs.created")}>
              {when(run.created_at)}
            </MetaRow>
            <MetaRow label={t("audit.retrieval.runs.started")}>
              {when(run.started_at)}
            </MetaRow>
            <MetaRow label={t("audit.retrieval.runs.finished")}>
              {when(run.finished_at)}
            </MetaRow>
            <MetaRow label={t("audit.retrieval.runs.heartbeat")}>
              {when(run.heartbeat_at)}
            </MetaRow>
            {payload?.detail.duration_seconds != null && (
              <MetaRow label={t("audit.retrieval.runs.duration")}>
                {Math.round(payload.detail.duration_seconds)}s
              </MetaRow>
            )}
            {run.budget_tokens != null && (
              <MetaRow label={t("audit.retrieval.runs.budget")}>
                {formatNumber(run.budget_tokens)}
              </MetaRow>
            )}
            <MetaRow label={t("audit.retrieval.runs.idempotency")}>
              <span className="break-all font-mono text-[11px]">
                {run.idempotency_key ?? "—"}
              </span>
            </MetaRow>
          </dl>

          {run.progress_detail && (
            <div
              className="rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-muted)] p-3"
              data-testid="retrieval-run-live-progress"
            >
              <p className="mb-2 text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
                {t("audit.retrieval.runs.liveProgress")}
              </p>
              <RetrievalProgress
                detail={run.progress_detail}
                testId="retrieval-run-progress"
              />
            </div>
          )}

          {result ? (
            <div
              className="rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-muted)] p-3"
              data-testid="retrieval-run-result"
            >
              <p className="mb-2 text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
                {t("audit.retrieval.runs.result")}
              </p>
              <div className="flex flex-wrap gap-3 text-xs text-[var(--as-fg)]">
                <span>
                  {t("audit.retrieval.runs.scanned")}: {formatNumber(result.scanned)}
                </span>
                <span>
                  {t("audit.retrieval.runs.embedded")}: {formatNumber(result.embedded)}
                </span>
                <span>
                  {t("audit.retrieval.runs.skipped")}: {formatNumber(result.skipped)}
                </span>
                <span>
                  {t("audit.retrieval.runs.failed")}: {formatNumber(result.failed)}
                </span>
                <GateBadge gate={result.gate} />
              </div>
            </div>
          ) : (
            <p className="text-xs text-[var(--as-muted-fg)]">
              {payload?.result_state === "absent"
                ? t("audit.retrieval.runs.noResult")
                : t("audit.retrieval.runs.resultUnreadable")}
            </p>
          )}

          {failedIds.length > 0 && (
            <div data-testid="retrieval-run-failed-ids">
              <p className="mb-1 flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
                <span>{t("audit.retrieval.runs.failedIds")}</span>
                <span className="tabular-nums">
                  {t("audit.retrieval.runs.failedIdsCount", {
                    shown: shownIds.length,
                    total: failedIds.length,
                  })}
                </span>
                {truncated && (
                  <Badge variant="warning" data-testid="retrieval-run-failed-truncated">
                    {t("audit.retrieval.runs.truncated", {
                      limit: payload?.failed_ids_limit ?? failedIds.length,
                    })}
                  </Badge>
                )}
              </p>
              <ul className="flex max-h-48 flex-wrap gap-1 overflow-y-auto">
                {shownIds.map((id) => (
                  <li
                    key={id}
                    className="break-all rounded-[var(--as-radius)] bg-[var(--as-muted)] px-2 py-0.5 font-mono text-[11px] text-[var(--as-fg)]"
                  >
                    {id}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {run.error && (
            <div data-testid="retrieval-run-error">
              <p className="mb-1 text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
                {t("audit.retrieval.runs.error")}
              </p>
              <p className="max-h-40 overflow-y-auto break-words rounded-[var(--as-radius)] bg-rose-50 p-2 text-xs text-rose-700">
                {run.error}
              </p>
            </div>
          )}

          {payload?.detail.activation_gate && (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-[var(--as-muted-fg)]">
                {t("audit.retrieval.runs.activationGate")}:
              </span>
              <GateBadge gate={payload.detail.activation_gate.coverage} />
              <GateBadge gate={payload.detail.activation_gate.quality} />
            </div>
          )}

          <Link
            to={TOOLS_RETRIEVAL_URL}
            className="inline-flex text-xs font-semibold text-[var(--as-primary)] hover:underline"
            data-testid="retrieval-run-tools-link"
          >
            {t("audit.retrieval.runs.manageInTools")} →
          </Link>
        </div>
      ) : null}
    </PanelModal>
  );
}
