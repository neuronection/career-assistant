import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  fetchRetrievalCoverage,
  fetchRetrievalHealth,
  fetchRetrievalSpaces,
  type RetrievalCoverage,
  type RetrievalHealth,
  type RetrievalSpace,
} from "@/api/retrieval";
import { apiDetail } from "@/api/client";
import { Badge, PanelModal, Spinner } from "@/components/ui";
import { GateBadge } from "@/components/audit/retrieval/RetrievalCommon";
import {
  formatNumber,
  formatRate,
  shortId,
  statusVariant,
  TOOLS_RETRIEVAL_URL,
  when,
} from "@/components/audit/retrieval/retrievalHelpers";

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

/** The Spaces-section drawer: lifecycle/model/coverage/health, read-only.
 * Mutations and reindex links point at Tools → Retrieval. */
export function RetrievalSpaceDrawer({
  spaceId,
  onClose,
}: {
  spaceId: string | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [space, setSpace] = useState<RetrievalSpace | null>(null);
  const [coverage, setCoverage] = useState<RetrievalCoverage | null>(null);
  const [health, setHealth] = useState<RetrievalHealth | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!spaceId) {
      setSpace(null);
      setCoverage(null);
      setHealth(null);
      setError("");
      return;
    }
    let live = true;
    setLoading(true);
    Promise.all([
      fetchRetrievalSpaces(),
      fetchRetrievalCoverage(spaceId),
      fetchRetrievalHealth(),
    ])
      .then(([spaces, coverageResult, healthResult]) => {
        if (!live) return;
        const found = spaces.spaces.find((row) => row.space_id === spaceId) ?? null;
        setSpace(found);
        setCoverage(coverageResult);
        setHealth(healthResult);
        setError(found ? "" : t("audit.retrieval.spaces.notFound"));
      })
      .catch((err) => {
        if (live) {
          setSpace(null);
          setCoverage(null);
          setHealth(null);
          setError(apiDetail(err));
        }
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [spaceId, t]);

  const spaceHealth =
    health?.spaces.find((row) => row.space_id === spaceId) ?? null;

  return (
    <PanelModal
      open={spaceId !== null}
      onOpenChange={(open) => !open && onClose()}
      title={
        space
          ? t("audit.retrieval.spaces.drawerTitle", { name: space.name })
          : t("audit.retrieval.spaces.drawerTitleFallback")
      }
      size="lg"
      data-testid="retrieval-space-drawer"
    >
      {loading ? (
        <div className="py-8">
          <Spinner />
        </div>
      ) : error ? (
        <p className="text-sm text-rose-600" role="alert">
          {error}
        </p>
      ) : space ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={statusVariant(space.status)}>
              {t(`retrieval.spaceStatus.${space.status}`)}
            </Badge>
            <GateBadge gate={space.gate} />
            {spaceHealth && (
              <Badge
                variant={spaceHealth.ok ? "success" : "danger"}
                data-testid="retrieval-space-health"
              >
                {spaceHealth.ok
                  ? t("retrieval.active.healthOk")
                  : t("retrieval.active.healthFailed")}
              </Badge>
            )}
          </div>

          <dl className="space-y-1" data-testid="retrieval-space-meta">
            <MetaRow label={t("audit.retrieval.spaces.id")}>
              <span className="font-mono text-[11px]">{space.space_id}</span>
            </MetaRow>
            <MetaRow label={t("retrieval.active.backend")}>
              {space.backend}
            </MetaRow>
            <MetaRow label={t("retrieval.active.model")}>
              {space.provider}/{space.model} · {space.dim}
            </MetaRow>
            <MetaRow label={t("audit.retrieval.spaces.metric")}>
              {space.metric}
            </MetaRow>
            <MetaRow label={t("audit.retrieval.spaces.indexTable")}>
              <span className="font-mono text-[11px]">
                {space.index_table ?? "—"}
              </span>
            </MetaRow>
            <MetaRow label={t("retrieval.active.documents")}>
              {formatNumber(space.documents)}
            </MetaRow>
            <MetaRow label={t("retrieval.active.records")}>
              {formatNumber(space.records)}
            </MetaRow>
            <MetaRow label={t("retrieval.active.coverage")}>
              {space.coverage == null
                ? t("retrieval.state.never_reconciled")
                : formatRate(space.coverage)}
            </MetaRow>
            <MetaRow label={t("audit.retrieval.spaces.staleFailed", {
              stale: space.stale ?? 0,
              failed: space.failed ?? 0,
            })}>
              {space.as_of ? when(space.as_of) : "—"}
            </MetaRow>
            <MetaRow label={t("audit.retrieval.spaces.created")}>
              {when(space.created_at)}
            </MetaRow>
            <MetaRow label={t("audit.retrieval.spaces.activated")}>
              {when(space.activated_at)}
            </MetaRow>
            <MetaRow label={t("retrieval.active.lastReindex")}>
              {when(space.last_reindex_at)}
            </MetaRow>
          </dl>

          {space.last_error && (
            <p className="break-words rounded-[var(--as-radius)] bg-rose-50 p-2 text-xs text-rose-700">
              {space.last_error}
            </p>
          )}

          {coverage && (
            <div data-testid="retrieval-space-coverage">
              <p className="mb-1 text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
                {t("audit.retrieval.spaces.coverageByKind")}
              </p>
              {coverage.state === "never_reconciled" ? (
                <p className="text-xs text-[var(--as-muted-fg)]">
                  {t("retrieval.state.never_reconciled")}
                </p>
              ) : (
                <ul className="space-y-1">
                  {coverage.kinds.map((entry) => (
                    <li
                      key={entry.kind}
                      className="flex items-center justify-between gap-2 text-xs"
                    >
                      <span>{t(`retrieval.kind.${entry.kind}`, { defaultValue: entry.kind })}</span>
                      <span className="tabular-nums text-[var(--as-muted-fg)]">
                        {formatRate(entry.coverage.coverage)} ·{" "}
                        {t("audit.retrieval.spaces.embeddedOf", {
                          embedded: formatNumber(entry.coverage.embedded),
                          total: formatNumber(entry.coverage.total),
                        })}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {spaceHealth?.detail && (
            <p className="text-xs text-[var(--as-muted-fg)]">
              {t("retrieval.active.health")}: {spaceHealth.detail}
            </p>
          )}

          <Link
            to={TOOLS_RETRIEVAL_URL}
            className="inline-flex text-xs font-semibold text-[var(--as-primary)] hover:underline"
            data-testid="retrieval-space-tools-link"
          >
            {t("audit.retrieval.spaces.manageInTools")} →
          </Link>
          <span className="ml-2 font-mono text-[10px] text-[var(--as-muted-fg)]">
            {shortId(space.space_id)}
          </span>
        </div>
      ) : null}
    </PanelModal>
  );
}
