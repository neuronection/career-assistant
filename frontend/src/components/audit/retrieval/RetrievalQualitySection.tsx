import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  fetchRetrievalQuality,
  fetchRetrievalSpaces,
  type RetrievalQuality,
  type RetrievalQualityQueryResult,
  type RetrievalWindow,
} from "@/api/retrieval";
import { apiDetail } from "@/api/client";
import { Badge, PanelModal } from "@/components/ui";
import {
  GateBadge,
  RetrievalError,
  RetrievalLoading,
  RetrievalSectionHeader,
  StateNote,
  tableShellClass,
  tableClass,
  tdClass,
  thClass,
} from "@/components/audit/retrieval/RetrievalCommon";
import {
  formatRate,
  shortId,
  TOOLS_RETRIEVAL_URL,
  when,
} from "@/components/audit/retrieval/retrievalHelpers";
import { Link } from "react-router-dom";

export function RetrievalQualitySection({
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
  const [quality, setQuality] = useState<RetrievalQuality | null>(null);
  const [noSpace, setNoSpace] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    setLoading(true);
    fetchRetrievalSpaces()
      .then((spaces) => {
        const space =
          spaces.spaces.find((row) => row.status === "active") ??
          spaces.spaces[0] ??
          null;
        if (!space) {
          if (live) {
            setNoSpace(true);
            setQuality(null);
            setError("");
          }
          return null;
        }
        if (live) setNoSpace(false);
        return fetchRetrievalQuality(space.space_id, window);
      })
      .then((loaded) => {
        if (!live || !loaded) return;
        setQuality(loaded);
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

  const queries = useMemo(
    () => quality?.quality?.queries ?? quality?.compare?.queries ?? [],
    [quality],
  );
  const selectedQuery =
    queries.find((query) => query.query_id === detailId) ?? null;

  if (loading) return <RetrievalLoading />;
  if (error) return <RetrievalError message={error} />;

  const header = (
    <RetrievalSectionHeader
      title={t("audit.retrieval.quality.title")}
      hint={t("audit.retrieval.quality.hint")}
      actions={
        <Link
          to={TOOLS_RETRIEVAL_URL}
          className="inline-flex items-center py-1 text-xs font-semibold text-[var(--as-primary)] hover:underline"
          data-testid="retrieval-quality-tools-link"
        >
          {t("audit.retrieval.quality.manageInTools")} →
        </Link>
      }
    />
  );

  if (noSpace) {
    return (
      <div className="space-y-3" data-testid="retrieval-quality">
        {header}
        <div data-testid="retrieval-quality-no-space">
          <StateNote>{t("audit.retrieval.quality.noSpace")}</StateNote>
        </div>
      </div>
    );
  }

  if (!quality) return null;

  const block = quality.quality;
  const compare = quality.compare;
  const noGolden = quality.state === "no_golden_set";
  const notSampled = quality.state === "not_sampled";
  const stale = quality.state === "stale_compare";

  return (
    <div className="space-y-3" data-testid="retrieval-quality">
      {header}
      {noGolden ? (
        <div data-testid="retrieval-quality-no-golden">
          <StateNote>{t("retrieval.state.no_golden_set")}</StateNote>
        </div>
      ) : notSampled ? (
        <div data-testid="retrieval-quality-not-sampled">
          <StateNote>{t("audit.retrieval.quality.notSampled")}</StateNote>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            {quality.set && (
              <span className="text-xs text-[var(--as-muted-fg)]">
                {t("retrieval.quality.setVersion", {
                  version: quality.set.set_version,
                  count: quality.set.query_count,
                })}
              </span>
            )}
            {quality.set && (
              <span className="text-xs text-[var(--as-muted-fg)]">
                {t("audit.retrieval.quality.k", { k: quality.set.k })}
              </span>
            )}
            {block && (
              <GateBadge gate={block.passed ? "pass" : "fail"} />
            )}
            {compare && <GateBadge gate={compare.passed ? "pass" : "fail"} />}
            {stale && (
              <Badge variant="warning" data-testid="retrieval-quality-stale">
                {t("retrieval.state.stale_compare")}
              </Badge>
            )}
          </div>

          {compare ? (
            <div
              className="grid gap-3 rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4 sm:grid-cols-2"
              data-testid="retrieval-quality-compare"
            >
              <ScoreBlock
                title={t("audit.retrieval.quality.baseline", {
                  id: shortId(compare.old_space_id),
                })}
                recall={compare.old_recall_at_k}
                precision={compare.old_precision_at_k}
                floorRecall={compare.floor_recall}
                floorPrecision={compare.floor_precision}
              />
              <ScoreBlock
                title={t("audit.retrieval.quality.candidate", {
                  id: shortId(compare.new_space_id),
                })}
                recall={compare.new_recall_at_k}
                precision={compare.new_precision_at_k}
                floorRecall={compare.floor_recall}
                floorPrecision={compare.floor_precision}
              />
              <p className="text-xs text-[var(--as-muted-fg)] sm:col-span-2">
                {t("audit.retrieval.quality.compareMeta", {
                  version: compare.set_version,
                  k: compare.k,
                  when: when(compare.generated_at),
                })}
              </p>
            </div>
          ) : block ? (
            <div
              className="grid gap-3 rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4 sm:grid-cols-2"
              data-testid="retrieval-quality-block"
            >
              <ScoreBlock
                title={t("audit.retrieval.quality.space", {
                  id: shortId(block.space_id),
                })}
                recall={block.recall_at_k}
                precision={block.precision_at_k}
                floorRecall={block.floor_recall}
                floorPrecision={block.floor_precision}
              />
              <p className="text-xs text-[var(--as-muted-fg)]">
                {t("audit.retrieval.quality.generated", {
                  when: when(block.generated_at),
                })}
              </p>
            </div>
          ) : null}

          {queries.length === 0 ? (
            <StateNote>{t("audit.retrieval.quality.noQueries")}</StateNote>
          ) : (
            <div
              className={tableShellClass}
              tabIndex={0}
              role="region"
              aria-label={t("audit.retrieval.quality.colQuery")}
              data-testid="retrieval-quality-queries"
            >
              <table className={tableClass}>
                <thead>
                  <tr className="border-b border-[var(--as-border)]">
                    <th className={thClass}>
                      {t("audit.retrieval.quality.colQuery")}
                    </th>
                    <th className={thClass}>
                      {t("retrieval.quality.recall")}
                    </th>
                    <th className={thClass}>
                      {t("retrieval.quality.precision")}
                    </th>
                    <th className={thClass}>
                      {t("audit.retrieval.quality.colMissing")}
                    </th>
                    <th className={thClass}>
                      {t("audit.retrieval.quality.colResult")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {queries.map((query) => (
                    <tr
                      key={query.query_id}
                      className="cursor-pointer border-b border-[var(--as-border)] last:border-b-0 hover:bg-[var(--as-muted)]"
                      onClick={() => onOpenDetail(query.query_id)}
                      data-testid={`retrieval-quality-query-row-${query.query_id}`}
                    >
                      <td className={`${tdClass} font-mono text-[11px]`}>
                        <button
                          type="button"
                          className="max-w-full break-all rounded text-left font-mono underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-accent)]"
                          aria-label={t("audit.retrieval.quality.openRow", {
                            id: query.query_id,
                          })}
                          onClick={(event) => {
                            event.stopPropagation();
                            onOpenDetail(query.query_id);
                          }}
                          data-testid={`retrieval-quality-query-open-${query.query_id}`}
                        >
                          {query.query_id}
                        </button>
                      </td>
                      <td className={`${tdClass} tabular-nums`}>
                        {formatRate(query.recall_at_k)}
                      </td>
                      <td className={`${tdClass} tabular-nums`}>
                        {formatRate(query.precision_at_k)}
                      </td>
                      <td className={`${tdClass} tabular-nums`}>
                        {query.missing_document_ids.length}
                      </td>
                      <td className={tdClass}>
                        <Badge variant={query.passed ? "success" : "danger"}>
                          {query.passed
                            ? t("retrieval.gate.pass")
                            : t("retrieval.gate.fail")}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      <QualityQueryDrawer query={selectedQuery} onClose={onCloseDetail} />
    </div>
  );
}

function ScoreBlock({
  title,
  recall,
  precision,
  floorRecall,
  floorPrecision,
}: {
  title: string;
  recall: number;
  precision: number;
  floorRecall: number;
  floorPrecision: number;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-1">
      <p className="text-xs font-semibold text-[var(--as-fg)]">{title}</p>
      <dl className="space-y-1 text-xs">
        <div className="flex justify-between gap-2">
          <dt className="text-[var(--as-muted-fg)]">{t("retrieval.quality.recall")}</dt>
          <dd className="tabular-nums text-[var(--as-fg)]">
            {formatRate(recall)}{" "}
            <span className="text-[var(--as-muted-fg)]">
              ({t("retrieval.quality.floor", { value: formatRate(floorRecall) })})
            </span>
          </dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-[var(--as-muted-fg)]">
            {t("retrieval.quality.precision")}
          </dt>
          <dd className="tabular-nums text-[var(--as-fg)]">
            {formatRate(precision)}{" "}
            <span className="text-[var(--as-muted-fg)]">
              ({t("retrieval.quality.floor", { value: formatRate(floorPrecision) })})
            </span>
          </dd>
        </div>
      </dl>
    </div>
  );
}

function IdList({ ids, testId }: { ids: string[]; testId: string }) {
  if (ids.length === 0) {
    return <p className="text-xs text-[var(--as-muted-fg)]">—</p>;
  }
  return (
    <ul className="flex max-h-40 flex-wrap gap-1 overflow-y-auto" data-testid={testId}>
      {ids.map((id) => (
        <li
          key={id}
          className="break-all rounded-[var(--as-radius)] bg-[var(--as-muted)] px-2 py-0.5 font-mono text-[11px] text-[var(--as-fg)]"
        >
          {id}
        </li>
      ))}
    </ul>
  );
}

function QualityQueryDrawer({
  query,
  onClose,
}: {
  query: RetrievalQualityQueryResult | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <PanelModal
      open={query !== null}
      onOpenChange={(open) => !open && onClose()}
      title={
        query
          ? t("audit.retrieval.quality.queryDrawerTitle", {
              id: query.query_id,
            })
          : t("audit.retrieval.quality.queryDrawerFallback")
      }
      data-testid="retrieval-quality-drawer"
    >
      {query && (
        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={query.passed ? "success" : "danger"}>
              {query.passed ? t("retrieval.gate.pass") : t("retrieval.gate.fail")}
            </Badge>
            <span className="text-xs text-[var(--as-muted-fg)]">
              {t("audit.retrieval.quality.queryId")}:{" "}
              <span className="font-mono text-[11px]">{query.query_id}</span>
            </span>
          </div>
          <dl className="grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-[var(--as-radius)] bg-[var(--as-muted)] p-2">
              <dt className="text-[var(--as-muted-fg)]">
                {t("retrieval.quality.recall")}
              </dt>
              <dd className="text-base font-semibold tabular-nums text-[var(--as-fg)]">
                {formatRate(query.recall_at_k)}
              </dd>
            </div>
            <div className="rounded-[var(--as-radius)] bg-[var(--as-muted)] p-2">
              <dt className="text-[var(--as-muted-fg)]">
                {t("retrieval.quality.precision")}
              </dt>
              <dd className="text-base font-semibold tabular-nums text-[var(--as-fg)]">
                {formatRate(query.precision_at_k)}
              </dd>
            </div>
          </dl>
          <div>
            <h3 className="mb-1 text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
              {t("audit.retrieval.quality.expected")}
            </h3>
            <IdList ids={query.expected_document_ids} testId="retrieval-quality-expected" />
          </div>
          <div>
            <h3 className="mb-1 text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
              {t("audit.retrieval.quality.retrieved")}
            </h3>
            <IdList ids={query.retrieved_document_ids} testId="retrieval-quality-retrieved" />
          </div>
          <div>
            <h3 className="mb-1 text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
              {t("audit.retrieval.quality.missing")}
            </h3>
            <IdList ids={query.missing_document_ids} testId="retrieval-quality-missing" />
          </div>
          <p className="text-[11px] text-[var(--as-muted-fg)]">
            {t("audit.retrieval.quality.noRawQuery")}
          </p>
        </div>
      )}
    </PanelModal>
  );
}
