import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  fetchRetrievalSpaces,
  type RetrievalSpace,
  type RetrievalSpacesResponse,
} from "@/api/retrieval";
import { apiDetail } from "@/api/client";
import { Badge } from "@/components/ui";
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
import { RetrievalSpaceDrawer } from "@/components/audit/retrieval/RetrievalSpaceDrawer";
import {
  formatNumber,
  formatRate,
  statusVariant,
  TOOLS_RETRIEVAL_URL,
  when,
} from "@/components/audit/retrieval/retrievalHelpers";

export function RetrievalSpacesSection({
  detailId,
  onOpenDetail,
  onCloseDetail,
}: {
  detailId: string | null;
  onOpenDetail: (id: string) => void;
  onCloseDetail: () => void;
}) {
  const { t } = useTranslation();
  const [data, setData] = useState<RetrievalSpacesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    setLoading(true);
    fetchRetrievalSpaces()
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
  }, []);

  if (loading) return <RetrievalLoading />;
  if (error) return <RetrievalError message={error} />;

  const spaces = data?.spaces ?? [];

  return (
    <div className="space-y-3" data-testid="retrieval-spaces">
      <RetrievalSectionHeader
        title={t("audit.retrieval.spaces.title")}
        hint={t("audit.retrieval.spaces.hint", {
          backend: data?.backend.label ?? "—",
        })}
        actions={
          <Link
            to={TOOLS_RETRIEVAL_URL}
            className="inline-flex items-center py-1 text-xs font-semibold text-[var(--as-primary)] hover:underline"
            data-testid="retrieval-spaces-tools-link"
          >
            {t("audit.retrieval.openTools")} →
          </Link>
        }
      />

      {spaces.length === 0 ? (
        <div data-testid="retrieval-spaces-empty">
          <StateNote>{t("audit.retrieval.spaces.empty")}</StateNote>
        </div>
      ) : (
        <div
          className={tableShellClass}
          tabIndex={0}
          role="region"
          aria-label={t("audit.retrieval.spaces.title")}
        >
          <table className={tableClass}>
            <thead>
              <tr className="border-b border-[var(--as-border)]">
                <th className={thClass}>{t("audit.retrieval.spaces.colName")}</th>
                <th className={thClass}>{t("audit.retrieval.spaces.colStatus")}</th>
                <th className={thClass}>{t("retrieval.active.model")}</th>
                <th className={thClass}>{t("audit.retrieval.spaces.colIndex")}</th>
                <th className={thClass}>{t("retrieval.active.documents")}</th>
                <th className={thClass}>{t("retrieval.active.records")}</th>
                <th className={thClass}>{t("retrieval.active.coverage")}</th>
                <th className={thClass}>{t("retrieval.gateLabel.coverage")}</th>
                <th className={thClass}>{t("audit.retrieval.spaces.colCreated")}</th>
                <th className={thClass}>{t("audit.retrieval.spaces.colActivated")}</th>
              </tr>
            </thead>
            <tbody>
              {spaces.map((space) => (
                <SpaceRow key={space.space_id} space={space} onOpen={onOpenDetail} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <RetrievalSpaceDrawer
        spaceId={detailId}
        onClose={onCloseDetail}
      />
    </div>
  );
}

function SpaceRow({
  space,
  onOpen,
}: {
  space: RetrievalSpace;
  onOpen: (id: string) => void;
}) {
  const { t } = useTranslation();
  const cold = space.coverage == null;
  return (
    <tr
      className="cursor-pointer border-b border-[var(--as-border)] last:border-b-0 hover:bg-[var(--as-muted)]"
      onClick={() => onOpen(space.space_id)}
      data-testid={`retrieval-space-row-${space.space_id}`}
    >
      <td className={`${tdClass} font-medium`}>
        <button
          type="button"
          className="max-w-full rounded text-left font-medium underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-accent)]"
          title={space.space_id}
          aria-label={t("audit.retrieval.spaces.openRow", { name: space.name })}
          onClick={(event) => {
            event.stopPropagation();
            onOpen(space.space_id);
          }}
          data-testid={`retrieval-space-open-${space.space_id}`}
        >
          {space.name}
        </button>
      </td>
      <td className={tdClass}>
        <Badge variant={statusVariant(space.status)}>
          {t(`retrieval.spaceStatus.${space.status}`)}
        </Badge>
      </td>
      <td className={tdClass}>
        {space.model} · {space.dim}
      </td>
      <td className={`${tdClass} font-mono text-[11px]`}>
        {space.index_table ?? "—"}
      </td>
      <td className={`${tdClass} tabular-nums`}>{formatNumber(space.documents)}</td>
      <td className={`${tdClass} tabular-nums`}>{formatNumber(space.records)}</td>
      <td className={`${tdClass} tabular-nums`}>
        {cold ? t("retrieval.state.never_reconciled") : formatRate(space.coverage)}
      </td>
      <td className={tdClass}>
        <GateBadge gate={space.gate} />
      </td>
      <td className={`${tdClass} text-[var(--as-muted-fg)]`}>
        {when(space.created_at)}
      </td>
      <td className={`${tdClass} text-[var(--as-muted-fg)]`}>
        {when(space.activated_at)}
      </td>
    </tr>
  );
}
