import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  fetchRetrievalFailures,
  type RetrievalFailureGroup,
  type RetrievalFailuresResponse,
  type RetrievalWindow,
} from "@/api/retrieval";
import { apiDetail } from "@/api/client";
import { Badge, PanelModal } from "@/components/ui";
import {
  RetrievalError,
  RetrievalLoading,
  RetrievalSectionHeader,
  StateNote,
} from "@/components/audit/retrieval/RetrievalCommon";
import {
  failureDetailId,
  formatNumber,
  parseFailureDetailId,
  retrievalRunUrl,
  TOOLS_RETRIEVAL_URL,
  when,
} from "@/components/audit/retrieval/retrievalHelpers";

const DOCUMENT_ID_LIMIT = 50;

export function RetrievalFailuresSection({
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
  const [data, setData] = useState<RetrievalFailuresResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    setLoading(true);
    fetchRetrievalFailures({ window })
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

  const groups = data?.groups ?? [];
  const selected =
    groups.find(
      (group) =>
        failureDetailId(group.kind, group.space_id, group.run_id) === detailId,
    ) ?? null;

  if (loading) return <RetrievalLoading />;
  if (error) return <RetrievalError message={error} />;

  return (
    <div className="space-y-3" data-testid="retrieval-failures">
      <RetrievalSectionHeader
        title={t("audit.retrieval.failures.title")}
        hint={t("audit.retrieval.failures.hint")}
        actions={
          <Link
            to={TOOLS_RETRIEVAL_URL}
            className="text-xs font-semibold text-[var(--as-primary)] hover:underline"
            data-testid="retrieval-failures-tools-link"
          >
            {t("audit.retrieval.failures.retryInTools")} →
          </Link>
        }
      />

      {data?.truncated && (
        <Badge variant="warning" data-testid="retrieval-failures-truncated">
          {t("audit.retrieval.failures.truncated")}
        </Badge>
      )}

      {groups.length === 0 ? (
        <div data-testid="retrieval-failures-empty">
          <StateNote>{t("audit.retrieval.failures.empty")}</StateNote>
        </div>
      ) : (
        <div className="grid gap-2">
          {groups.map((group) => {
            const id = failureDetailId(group.kind, group.space_id, group.run_id);
            return (
              <button
                key={id}
                type="button"
                className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3 text-left transition-colors hover:bg-[var(--as-surface-raised)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-accent)]"
                onClick={() => onOpenDetail(id)}
                data-testid={`retrieval-failure-group-${id}`}
              >
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-[var(--as-fg)]">
                    {t(`audit.retrieval.failureKind.${group.kind}`, {
                      defaultValue: group.kind,
                    })}
                  </span>
                  <Badge variant="danger">
                    {t("audit.retrieval.failures.count", {
                      count: formatNumber(group.count),
                    })}
                  </Badge>
                  {group.reason && (
                    <Badge variant="secondary">
                      {t(`audit.retrieval.reason.${group.reason}`, {
                        defaultValue: group.reason,
                      })}
                    </Badge>
                  )}
                  {group.retryable && (
                    <Badge variant="warning">
                      {t("audit.retrieval.failures.retryable")}
                    </Badge>
                  )}
                </span>
                <span className="mt-1 flex flex-wrap gap-3 text-xs text-[var(--as-muted-fg)]">
                  <span>
                    {t("audit.retrieval.failures.space")}:{" "}
                    <span className="font-mono text-[11px]">
                      {group.space_id.slice(0, 8)}
                    </span>
                  </span>
                  <span>
                    {t("audit.retrieval.failures.lastSeen")}: {when(group.last_seen)}
                  </span>
                  {group.document_ids.length > 0 && (
                    <span>
                      {t("audit.retrieval.failures.documents", {
                        count: group.document_ids.length,
                      })}
                    </span>
                  )}
                </span>
              </button>
            );
          })}
        </div>
      )}

      <FailureDrawer
        group={selected}
        window={window}
        onClose={onCloseDetail}
      />
    </div>
  );
}

function FailureDrawer({
  group,
  window,
  onClose,
}: {
  group: RetrievalFailureGroup | null;
  window: RetrievalWindow;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const detail = parseFailureDetailId(
    group ? failureDetailId(group.kind, group.space_id, group.run_id) : null,
  );
  const shownIds = (group?.document_ids ?? []).slice(0, DOCUMENT_ID_LIMIT);
  return (
    <PanelModal
      open={group !== null}
      onOpenChange={(open) => !open && onClose()}
      title={
        group
          ? t(`audit.retrieval.failureKind.${group.kind}`, {
              defaultValue: group.kind,
            })
          : t("audit.retrieval.failures.drawerTitle")
      }
      data-testid="retrieval-failure-drawer"
    >
      {group && detail && (
        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="danger">
              {t("audit.retrieval.failures.count", {
                count: formatNumber(group.count),
              })}
            </Badge>
            {group.reason && (
              <Badge variant="secondary">
                {t(`audit.retrieval.reason.${group.reason}`, {
                  defaultValue: group.reason,
                })}
              </Badge>
            )}
          </div>
          <dl className="space-y-1 text-xs" data-testid="retrieval-failure-meta">
            <div className="flex justify-between gap-2">
              <dt className="text-[var(--as-muted-fg)]">
                {t("audit.retrieval.failures.reasonCode")}
              </dt>
              <dd className="font-mono text-[11px]">
                {group.reason ?? group.kind}
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-[var(--as-muted-fg)]">
                {t("audit.retrieval.failures.space")}
              </dt>
              <dd className="font-mono text-[11px]">{group.space_id}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-[var(--as-muted-fg)]">
                {t("audit.retrieval.failures.lastSeen")}
              </dt>
              <dd>{when(group.last_seen)}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-[var(--as-muted-fg)]">
                {t("audit.retrieval.failures.retryable")}
              </dt>
              <dd>
                {group.retryable
                  ? t("audit.retrieval.failures.yes")
                  : t("audit.retrieval.failures.no")}
              </dd>
            </div>
          </dl>

          {group.document_ids.length > 0 && (
            <div data-testid="retrieval-failure-documents">
              <p className="mb-1 text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
                {t("audit.retrieval.failures.documentIds", {
                  shown: shownIds.length,
                  total: group.document_ids.length,
                })}
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

          <div className="flex flex-wrap items-center gap-3">
            {group.run_id && (
              <Link
                to={retrievalRunUrl(group.run_id, window)}
                className="text-xs font-semibold text-[var(--as-primary)] hover:underline"
                data-testid="retrieval-failure-run-link"
              >
                {t("audit.retrieval.failures.openRun")} →
              </Link>
            )}
            {group.retryable && (
              <Link
                to={TOOLS_RETRIEVAL_URL}
                className="text-xs font-semibold text-[var(--as-primary)] hover:underline"
                data-testid="retrieval-failure-retry-link"
              >
                {t("audit.retrieval.failures.retryInTools")} →
              </Link>
            )}
          </div>
          <p className="text-[11px] text-[var(--as-muted-fg)]">
            {t("audit.retrieval.failures.structuredOnly")}
          </p>
        </div>
      )}
    </PanelModal>
  );
}
