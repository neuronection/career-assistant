import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  fetchRetrievalRuns,
  fetchRetrievalSpaces,
  type RetrievalRun,
  type RetrievalRunsResponse,
  type RetrievalRunStatus,
  type RetrievalSpacesResponse,
  type RetrievalWindow,
} from "@/api/retrieval";
import { apiDetail } from "@/api/client";
import { Badge } from "@/components/ui";
import {
  RetrievalError,
  RetrievalLoading,
  RetrievalSectionHeader,
  StateNote,
  tableShellClass,
  tableClass,
  tdClass,
  thClass,
} from "@/components/audit/retrieval/RetrievalCommon";
import { RetrievalRunDrawer } from "@/components/audit/retrieval/RetrievalRunDrawer";
import {
  shortId,
  statusVariant,
  TOOLS_RETRIEVAL_URL,
  when,
} from "@/components/audit/retrieval/retrievalHelpers";

const RUN_STATUSES: RetrievalRunStatus[] = [
  "queued",
  "running",
  "succeeded",
  "failed",
  "cancelled",
];
const RUN_KINDS = ["posting", "job", "profile", "skill"] as const;

const selectClass =
  "rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-3 py-2 text-sm text-[var(--as-fg)]";

export function RetrievalRunsSection({
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
  const [spaces, setSpaces] = useState<RetrievalSpacesResponse | null>(null);
  const [data, setData] = useState<RetrievalRunsResponse | null>(null);
  const [spaceFilter, setSpaceFilter] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    fetchRetrievalSpaces()
      .then((loaded) => {
        if (live) setSpaces(loaded);
      })
      .catch(() => {
        if (live) setSpaces(null);
      });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    let live = true;
    setLoading(true);
    fetchRetrievalRuns({
      window,
      ...(spaceFilter ? { space: spaceFilter } : {}),
      ...(kindFilter ? { kind: kindFilter } : {}),
      ...(statusFilter ? { status: statusFilter as RetrievalRunStatus } : {}),
      limit: 50,
    })
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
  }, [window, spaceFilter, kindFilter, statusFilter]);

  const runs = data?.runs ?? [];

  return (
    <div className="space-y-3" data-testid="retrieval-runs">
      <RetrievalSectionHeader
        title={t("audit.retrieval.runs.title")}
        hint={t("audit.retrieval.runs.hint")}
        actions={
          <Link
            to={TOOLS_RETRIEVAL_URL}
            className="inline-flex items-center py-1 text-xs font-semibold text-[var(--as-primary)] hover:underline"
            data-testid="retrieval-runs-tools-link"
          >
            {t("audit.retrieval.runs.manageInTools")} →
          </Link>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={t("retrieval.field.space")}
          className={selectClass}
          value={spaceFilter}
          onChange={(event) => setSpaceFilter(event.target.value)}
          data-testid="retrieval-runs-space-filter"
        >
          <option value="">{t("audit.retrieval.runs.allSpaces")}</option>
          {(spaces?.spaces ?? []).map((space) => (
            <option key={space.space_id} value={space.space_id}>
              {space.name} · {t(`retrieval.spaceStatus.${space.status}`)}
            </option>
          ))}
        </select>
        <select
          aria-label={t("retrieval.field.kind")}
          className={selectClass}
          value={kindFilter}
          onChange={(event) => setKindFilter(event.target.value)}
          data-testid="retrieval-runs-kind-filter"
        >
          <option value="">{t("retrieval.kind.all")}</option>
          {RUN_KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {t(`retrieval.kind.${kind}`)}
            </option>
          ))}
        </select>
        <select
          aria-label={t("audit.retrieval.runs.statusFilter")}
          className={selectClass}
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
          data-testid="retrieval-runs-status-filter"
        >
          <option value="">{t("audit.retrieval.runs.allStatuses")}</option>
          {RUN_STATUSES.map((status) => (
            <option key={status} value={status}>
              {t(`retrieval.status.${status}`)}
            </option>
          ))}
        </select>
        {data && data.unattributed_runs > 0 && (
          <Badge variant="secondary" data-testid="retrieval-runs-unattributed">
            {t("audit.retrieval.runs.unattributed", {
              count: data.unattributed_runs,
            })}
          </Badge>
        )}
        {data?.scan_truncated && (
          <Badge variant="warning" data-testid="retrieval-runs-scan-truncated">
            {t("audit.retrieval.runs.scanTruncated")}
          </Badge>
        )}
      </div>

      {error && <RetrievalError message={error} />}
      {loading ? (
        <RetrievalLoading />
      ) : runs.length === 0 ? (
        <div data-testid="retrieval-runs-empty">
          <StateNote>
            {data?.unattributed_runs
              ? t("audit.retrieval.runs.emptyUnattributed", {
                  count: data.unattributed_runs,
                })
              : t("audit.retrieval.runs.empty")}
          </StateNote>
        </div>
      ) : (
        <div
          className={tableShellClass}
          tabIndex={0}
          role="region"
          aria-label={t("audit.retrieval.runs.title")}
        >
          <table className={tableClass}>
            <thead>
              <tr className="border-b border-[var(--as-border)]">
                <th className={thClass}>{t("audit.retrieval.runs.colType")}</th>
                <th className={thClass}>{t("audit.retrieval.runs.colStatus")}</th>
                <th className={thClass}>{t("audit.retrieval.runs.colProgress")}</th>
                <th className={thClass}>{t("audit.retrieval.runs.colStage")}</th>
                <th className={thClass}>{t("audit.retrieval.runs.colScope")}</th>
                <th className={thClass}>{t("audit.retrieval.runs.colCreated")}</th>
                <th className={thClass}>{t("audit.retrieval.runs.colHeartbeat")}</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <RunRow key={run.run_id} run={run} onOpen={onOpenDetail} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <RetrievalRunDrawer runId={detailId} onClose={onCloseDetail} />
    </div>
  );
}

function RunRow({
  run,
  onOpen,
}: {
  run: RetrievalRun;
  onOpen: (id: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <tr
      className="cursor-pointer border-b border-[var(--as-border)] last:border-b-0 hover:bg-[var(--as-muted)]"
      onClick={() => onOpen(run.run_id)}
      data-testid={`retrieval-run-row-${run.run_id}`}
    >
      <td className={`${tdClass} font-medium`}>
        <button
          type="button"
          className="max-w-full rounded text-left font-medium underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-accent)]"
          title={run.run_id}
          aria-label={t("audit.retrieval.runs.openRow", {
            type: t(`retrieval.runType.${run.job_type}`),
            id: shortId(run.run_id),
          })}
          onClick={(event) => {
            event.stopPropagation();
            onOpen(run.run_id);
          }}
          data-testid={`retrieval-run-open-${run.run_id}`}
        >
          {t(`retrieval.runType.${run.job_type}`)}{" "}
          <span className="font-mono text-[10px] text-[var(--as-muted-fg)]">
            {shortId(run.run_id)}
          </span>
        </button>
      </td>
      <td className={tdClass}>
        <Badge variant={statusVariant(run.status)}>
          {t(`retrieval.status.${run.status}`)}
        </Badge>
      </td>
      <td className={`${tdClass} tabular-nums`}>{run.progress}%</td>
      <td className={tdClass}>{run.stage ?? "—"}</td>
      <td className={tdClass}>
        {run.scope.kind ?? t("retrieval.kind.all")} ·{" "}
        {run.scope.view ?? t("retrieval.view.all")}
      </td>
      <td className={`${tdClass} text-[var(--as-muted-fg)]`}>
        {when(run.created_at)}
      </td>
      <td className={`${tdClass} text-[var(--as-muted-fg)]`}>
        {when(run.heartbeat_at)}
      </td>
    </tr>
  );
}
