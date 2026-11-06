import { useTranslation } from "react-i18next";

import type { RetrievalRunProgress } from "@/api/retrieval";
import { Badge } from "@/components/ui";
import { formatNumber } from "@/components/audit/retrieval/retrievalHelpers";

/**
 * The live indexing bar for one vector run (plan 52 T4).
 *
 * Documents are exact at scan start; chunk totals are cumulative or
 * estimated, so the bar is driven by processed/total documents and the chunk
 * remainder is always labelled. Compact mode keeps the Tools run card and the
 * Audit runs table narrow; the drawer uses the full counter set.
 */
export function RetrievalProgress({
  detail,
  compact = false,
  testId = "retrieval-progress",
}: {
  detail: RetrievalRunProgress;
  compact?: boolean;
  testId?: string;
}) {
  const { t } = useTranslation();
  const total = Math.max(detail.total_documents, 0);
  const processed = Math.min(Math.max(detail.processed_documents, 0), total || Number.MAX_SAFE_INTEGER);
  const percent =
    total > 0
      ? Math.min(100, Math.round((processed / total) * 100))
      : detail.done
        ? 100
        : 0;
  const tokens = detail.tokens;

  return (
    <div className="min-w-0 space-y-1" data-testid={testId}>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--as-muted)]"
        role="progressbar"
        aria-label={t("retrieval.progress.aria", { percent })}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        data-testid={`${testId}-bar`}
      >
        <div
          className="h-full rounded-full bg-[var(--as-accent)] transition-[width] duration-500"
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-[var(--as-muted-fg)]">
        <span
          className="font-medium tabular-nums text-[var(--as-fg)]"
          data-testid={`${testId}-documents`}
        >
          {total > 0
            ? t("retrieval.progress.documents", {
                processed: formatNumber(processed),
                total: formatNumber(total),
              })
            : t("retrieval.progress.documentsNoTotal", {
                processed: formatNumber(processed),
              })}
        </span>
        {detail.done ? (
          <Badge variant="success" data-testid={`${testId}-done`}>
            {t("retrieval.progress.done")}
          </Badge>
        ) : null}
        {detail.chunks_estimated && !detail.done && (
          <span data-testid={`${testId}-estimated`}>
            {t("retrieval.progress.chunksEstimated")}
          </span>
        )}
        {detail.pending_chunks > 0 && (
          <span className="tabular-nums" data-testid={`${testId}-pending`}>
            {t("retrieval.progress.chunksPending", {
              count: formatNumber(detail.pending_chunks),
            })}
          </span>
        )}
        {!compact && (
          <>
            <span className="tabular-nums" data-testid={`${testId}-embedded`}>
              {t("retrieval.progress.embeddedDocuments", {
                count: formatNumber(detail.embedded_documents),
              })}
              {" · "}
              {t("retrieval.progress.embeddedChunks", {
                count: formatNumber(detail.embedded_chunks),
              })}
            </span>
            {(detail.skipped_documents > 0 || detail.skipped_chunks > 0) && (
              <span className="tabular-nums" data-testid={`${testId}-skipped`}>
                {t("retrieval.progress.skippedDocuments", {
                  count: formatNumber(detail.skipped_documents),
                })}
              </span>
            )}
            {(detail.failed_documents > 0 || detail.failed_chunks > 0) && (
              <span
                className="tabular-nums text-rose-600"
                data-testid={`${testId}-failed`}
              >
                {t("retrieval.progress.failedDocuments", {
                  count: formatNumber(detail.failed_documents),
                })}
              </span>
            )}
            {tokens != null && (
              <span className="tabular-nums" data-testid={`${testId}-tokens`}>
                {detail.tokens_estimated
                  ? t("retrieval.progress.tokensApprox", {
                      count: formatNumber(tokens),
                    })
                  : t("retrieval.progress.tokens", {
                      count: formatNumber(tokens),
                    })}
              </span>
            )}
            {detail.embed_calls > 0 && (
              <span className="tabular-nums" data-testid={`${testId}-calls`}>
                {t("retrieval.progress.embedCalls", {
                  count: formatNumber(detail.embed_calls),
                })}
              </span>
            )}
          </>
        )}
      </p>
    </div>
  );
}
