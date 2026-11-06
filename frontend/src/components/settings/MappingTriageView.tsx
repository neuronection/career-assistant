import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ChevronDown, Eye, ExternalLink, MapPin } from "lucide-react";

import {
  fetchMappingsQueue,
  fetchMappingsTrace,
  mappingActionError,
  mappingsExtract,
  mappingsGolden,
  mappingsIgnore,
  mappingsMap,
  mappingsRedecide,
  mappingsResolve,
  mappingsReview,
  mappingsUnignore,
  mappingsUnmap,
  type MappingBulkResult,
  type MappingFunnelState,
  type MappingQueueFilters,
  type MappingQueueResponse,
  type MappingTrace,
} from "@/api/mappings";
import { fetchAdminSources, type PostingSource } from "@/api/sources";
import { apiDetail } from "@/api/client";
import { Badge, Button, EmptyState, Spinner } from "@/components/ui";
import { EntityDetailsDrawer } from "@/components/settings/EntityDetailsDrawer";
import { JobTypePicker } from "@/components/settings/JobTypePicker";
import { TextField, TextareaField } from "@/features/cv/components/cv/formPrimitives";
import { SelectionEntry, SelectionToolbar } from "@/features/selection";
import { useListSelection } from "@/features/selection";

const PAGE = 50;

type BadgeTone = "default" | "success" | "warning" | "danger" | "secondary" | "outline";

const STATE_TONE: Record<MappingFunnelState, BadgeTone> = {
  mapped: "success",
  ignored: "secondary",
  no_description: "warning",
  detail_not_fetched: "warning",
  extract_failed: "danger",
  not_extracted: "warning",
  needs_review: "outline",
  semantic_unavailable: "outline",
  semantic_pending: "outline",
  no_skills: "secondary",
  below_threshold: "secondary",
  no_candidate: "secondary",
  unmapped_by_admin: "warning",
  unknown: "secondary",
};

const DETAIL_MODE_STATES = new Set<MappingFunnelState>([
  "not_extracted",
  "detail_not_fetched",
  "extract_failed",
]);

const IGNORE_REASONS = ["no_good_type", "multi_role", "not_a_job", "duplicate", "other"];

/**
 * The triage queue (plan 205 S3): filterable unmapped rows with the trace
 * drawer and the bounded bulk actions (extract, re-decide, map, unmap,
 * ignore, mark reviewed). Map is one posting at a time through the trace.
 */
export function MappingTriageView() {
  const { t } = useTranslation();
  const [filters, setFilters] = useState<MappingQueueFilters>({});
  const [queue, setQueue] = useState<MappingQueueResponse | null>(null);
  const [sources, setSources] = useState<PostingSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [traceId, setTraceId] = useState<string | null>(null);
  const [trace, setTrace] = useState<MappingTrace | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [mapJobId, setMapJobId] = useState<string | null>(null);
  const [bulkNote, setBulkNote] = useState<string | null>(null);
  const [bulkFailures, setBulkFailures] = useState<string[]>([]);
  const [ignorePanel, setIgnorePanel] = useState(false);
  const [ignoreReason, setIgnoreReason] = useState("no_good_type");
  const [ignoreNote, setIgnoreNote] = useState("");

  const load = useCallback(
    async (nextFilters: MappingQueueFilters, append: boolean) => {
      setLoading(true);
      setError(null);
      try {
        const page = await fetchMappingsQueue({ limit: PAGE, ...nextFilters });
        setQueue((previous) => {
          if (!append || !previous) return page;
          return {
            ...page,
            items: [...previous.items, ...page.items],
          };
        });
      } catch (caught) {
        setError(apiDetail(caught));
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load(filters, false);
  }, [filters, load]);

  useEffect(() => {
    fetchAdminSources()
      .then(setSources)
      .catch(() => setSources([]));
  }, []);

  useEffect(() => {
    if (!traceId) {
      setTrace(null);
      return;
    }
    setMapJobId(null);
    setTraceLoading(true);
    fetchMappingsTrace(traceId)
      .then((loaded) => {
        setTrace(loaded);
        setMapJobId(loaded.features.candidates[0]?.job_id ?? null);
      })
      .catch((caught) => setError(mappingActionError(caught)))
      .finally(() => setTraceLoading(false));
  }, [traceId]);

  const items = queue?.items ?? [];
  const selection = useListSelection({ allIds: items.map((row) => row.id), matchingIds: items.map((row) => row.id) });
  const selectedIds = useMemo(
    () => items.filter((row) => selection.ids.has(row.id)).map((row) => row.id),
    [items, selection.ids],
  );

  const runBulk = async (
    action: (ids: string[]) => Promise<MappingBulkResult>,
    confirmLabel: string,
  ) => {
    if (selectedIds.length === 0) return;
    if (!window.confirm(confirmLabel)) return;
    setBusy(true);
    setBulkNote(null);
    setBulkFailures([]);
    try {
      const result = await action(selectedIds);
      setBulkNote(t("mappingsConsole.triage.bulkDone", { count: result.affected }));
      selection.exit();
      await load(filters, false);
    } catch (caught) {
      setBulkFailures([mappingActionError(caught)]);
    } finally {
      setBusy(false);
    }
  };

  const resolveTrace = async (correct: boolean) => {
    if (!trace?.review_row || !traceId) return;
    setBusy(true);
    try {
      await mappingsResolve(trace.review_row.id, correct);
      setTrace(await fetchMappingsTrace(traceId));
      await load(filters, false);
    } catch (caught) {
      setError(mappingActionError(caught));
    } finally {
      setBusy(false);
    }
  };

  const mapTrace = async (jobId: string) => {
    if (!trace || !traceId) return;
    if (!window.confirm(t("mappingsConsole.triage.mapConfirm"))) return;
    setBusy(true);
    try {
      await mappingsMap(trace.posting.id, jobId);
      setTrace(await fetchMappingsTrace(traceId));
      await load(filters, false);
    } catch (caught) {
      setError(mappingActionError(caught));
    } finally {
      setBusy(false);
    }
  };

  const goldenFromTrace = async () => {
    if (!trace || !traceId) return;
    setBusy(true);
    try {
      await mappingsGolden(
        trace.posting.id,
        trace.posting.catalog_job_id ?? null,
      );
      setTrace(await fetchMappingsTrace(traceId));
    } catch (caught) {
      setError(mappingActionError(caught));
    } finally {
      setBusy(false);
    }
  };

  const stateCounts = queue?.states ?? {};
  const stateOptions = Object.entries(stateCounts).filter(([, count]) => count > 0);

  return (
    <div className="space-y-3" data-testid="mappings-triage">
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-sm">
          <span className="mr-1 text-slate-500">{t("mappingsConsole.triage.stateFilter")}</span>
          <select
            aria-label={t("mappingsConsole.triage.stateFilter")}
            value={filters.state ?? ""}
            onChange={(event) =>
              setFilters((current) => ({ ...current, state: event.target.value as MappingFunnelState | "" , cursor: undefined }))
            }
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
            data-testid="mappings-state-filter"
          >
            <option value="">{t("mappingsConsole.triage.allStates")}</option>
            {stateOptions.map(([state, count]) => (
              <option key={state} value={state}>
                {t(`mappingsConsole.state.${state}`)} ({count})
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mr-1 text-slate-500">{t("mappingsConsole.triage.sourceFilter")}</span>
          <select
            aria-label={t("mappingsConsole.triage.sourceFilter")}
            value={filters.source ?? ""}
            onChange={(event) =>
              setFilters((current) => ({ ...current, source: event.target.value, cursor: undefined }))
            }
            className="max-w-[14rem] rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
            data-testid="mappings-source-filter"
          >
            <option value="">{t("mappingsConsole.triage.allSources")}</option>
            {sources.map((source) => (
              <option key={source.id} value={source.id}>
                {source.title || source.key}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mr-1 text-slate-500">{t("mappingsConsole.triage.detailFilter")}</span>
          <select
            aria-label={t("mappingsConsole.triage.detailFilter")}
            value={filters.detail_state ?? ""}
            onChange={(event) =>
              setFilters((current) => ({
                ...current,
                detail_state: event.target.value as MappingQueueFilters["detail_state"],
                cursor: undefined,
              }))
            }
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
          >
            <option value="">{t("mappingsConsole.triage.detailAll")}</option>
            <option value="missing">{t("mappingsConsole.triage.detailMissing")}</option>
            <option value="fetched">{t("mappingsConsole.triage.detailFetched")}</option>
          </select>
        </label>
        <label className="text-sm">
          <span className="mr-1 text-slate-500">{t("mappingsConsole.triage.reviewFilter")}</span>
          <select
            aria-label={t("mappingsConsole.triage.reviewFilter")}
            value={String(filters.needs_review ?? "")}
            onChange={(event) =>
              setFilters((current) => ({
                ...current,
                needs_review:
                  event.target.value === "" ? "" : event.target.value === "true",
                cursor: undefined,
              }))
            }
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
          >
            <option value="">{t("mappingsConsole.triage.reviewAll")}</option>
            <option value="true">{t("mappingsConsole.triage.reviewFlagged")}</option>
            <option value="false">{t("mappingsConsole.triage.reviewClean")}</option>
          </select>
        </label>
        <div className="w-48" data-testid="mappings-q-filter">
          <TextField
            label={t("mappingsConsole.triage.search")}
            value={filters.q ?? ""}
            onChange={(value) =>
              setFilters((current) => ({ ...current, q: value, cursor: undefined }))
            }
          />
        </div>
        <span className="text-sm text-slate-500" data-testid="mappings-total">
          {t("mappingsConsole.triage.total", { count: queue?.total ?? 0 })}
        </span>
        <span className="grow" />
        <SelectionEntry prefix="mappings" selection={selection} />
      </div>

      {selection.active && (
        <SelectionToolbar
          prefix="mappings"
          selection={selection}
          allIds={items.map((row) => row.id)}
          matchingIds={items.map((row) => row.id)}
          busy={busy}
          actions={
            <>
          <Button
            variant="outline"
            size="sm"
            disabled={busy || selectedIds.length === 0}
            onClick={() => void runBulk((ids) => mappingsExtract(ids), t("mappingsConsole.triage.confirmExtract"))}
            data-testid="mappings-bulk-extract"
          >
            {t("mappingsConsole.triage.extract")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={busy || selectedIds.length === 0}
            onClick={() => void runBulk((ids) => mappingsRedecide(ids), t("mappingsConsole.triage.confirmRedecide"))}
            data-testid="mappings-bulk-redecide"
          >
            {t("mappingsConsole.triage.redecide")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={busy || selectedIds.length === 0}
            onClick={() => setIgnorePanel(true)}
            data-testid="mappings-bulk-ignore"
          >
            {t("mappingsConsole.triage.ignore")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={busy || selectedIds.length === 0}
            onClick={() => void runBulk((ids) => mappingsUnignore(ids), t("mappingsConsole.triage.confirmUnignore"))}
          >
            {t("mappingsConsole.triage.unignore")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={busy || selectedIds.length === 0}
            onClick={() => void runBulk((ids) => mappingsReview(ids, ignoreNote), t("mappingsConsole.triage.confirmReview"))}
            data-testid="mappings-bulk-review"
          >
            {t("mappingsConsole.triage.markReviewed")}
          </Button>
          <Button
            variant="destructive"
            size="sm"
            disabled={busy || selectedIds.length === 0}
            onClick={() => void runBulk((ids) => mappingsUnmap(ids), t("mappingsConsole.triage.confirmUnmap"))}
            data-testid="mappings-bulk-unmap"
          >
            {t("mappingsConsole.triage.unmap")}
          </Button>
            </>
          }
        />
      )}

      {ignorePanel && (
        <div
          className="flex flex-wrap items-end gap-2 rounded-lg border p-3"
          data-testid="mappings-ignore-panel"
        >
          <label className="text-sm">
            <span className="mr-1 text-slate-500">{t("mappingsConsole.triage.ignoreReason")}</span>
            <select
              aria-label={t("mappingsConsole.triage.ignoreReason")}
              value={ignoreReason}
              onChange={(event) => setIgnoreReason(event.target.value)}
              className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
            >
              {IGNORE_REASONS.map((reason) => (
                <option key={reason} value={reason}>
                  {t(`mappingsConsole.reviewReason.${reason}`)}
                </option>
              ))}
            </select>
          </label>
          <label className="grow text-sm">
            <span className="mr-1 text-slate-500">{t("mappingsConsole.triage.ignoreNote")}</span>
            <TextareaField
              label={t("mappingsConsole.triage.ignoreNote")}
              value={ignoreNote}
              onChange={(value) => setIgnoreNote(value)}
              rows={1}
            />
          </label>
          <Button
            size="sm"
            disabled={busy}
            onClick={() => {
              void runBulk(
                (ids) => mappingsIgnore(ids, ignoreReason, ignoreNote),
                t("mappingsConsole.triage.confirmIgnore"),
              ).then(() => {
                setIgnorePanel(false);
                setIgnoreNote("");
              });
            }}
            data-testid="mappings-ignore-confirm"
          >
            {t("mappingsConsole.triage.ignore")}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setIgnorePanel(false)}>
            {t("mappingsConsole.triage.cancel")}
          </Button>
        </div>
      )}

      {(bulkNote || bulkFailures.length > 0) && (
        <div className="space-y-1" data-testid="mappings-bulk-note">
          {bulkNote && <p className="text-sm text-slate-600">{bulkNote}</p>}
          {bulkFailures.map((failure) => (
            <p key={failure} className="text-sm text-red-600">
              {failure}
            </p>
          ))}
        </div>
      )}

      {error && <p className="text-sm text-red-600">{error}</p>}

      {loading && items.length === 0 ? (
        <div className="flex justify-center py-8">
          <Spinner className="h-6 w-6 text-slate-400" />
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          compact
          title={t("mappingsConsole.triage.queueEmptyTitle")}
          description={t("mappingsConsole.triage.queueEmptyBody")}
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm" data-testid="mappings-queue-table">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2">{t("mappingsConsole.triage.colPosting")}</th>
                <th className="px-3 py-2">{t("mappingsConsole.triage.colSource")}</th>
                <th className="px-3 py-2">{t("mappingsConsole.triage.colState")}</th>
                <th className="px-3 py-2">{t("mappingsConsole.triage.colCandidate")}</th>
                <th className="px-3 py-2">{t("mappingsConsole.triage.colAge")}</th>
                <th className="px-3 py-2" aria-label={t("mappingsConsole.triage.trace")} />
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr
                  key={row.id}
                  className="border-t"
                  data-testid="mappings-queue-row"
                  data-state={row.state}
                >
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      className="font-medium text-slate-900 underline-offset-2 hover:underline"
                      onClick={() => setTraceId(row.id)}
                    >
                      {row.title}
                    </button>
                    <span className="ml-2 text-xs text-slate-400">{row.ref}</span>
                    {row.needs_review && (
                      <Badge variant="outline" className="ml-2">
                        {t("mappingsConsole.triage.needsReview")}
                      </Badge>
                    )}
                    {row.review && (
                      <Badge variant="secondary" className="ml-2">
                        {t(`mappingsConsole.reviewReason.${row.review.reason}`)}
                      </Badge>
                    )}
                  </td>
                  <td className="px-3 py-2 text-slate-600">
                    {sources.find((source) => source.id === row.source_id)?.title ||
                      row.source_id.slice(0, 8)}
                  </td>
                  <td className="px-3 py-2">
                    <Badge variant={STATE_TONE[row.state]} data-testid="mappings-row-state">
                      {t(`mappingsConsole.state.${row.state}`)}
                    </Badge>
                  </td>
                  <td className="px-3 py-2 text-slate-600">
                    {row.top_candidate
                      ? `${row.top_candidate.job_code} (${row.top_candidate.deterministic ?? "—"})`
                      : "—"}
                  </td>
                  <td className="px-3 py-2 text-slate-500">
                    {row.created_at ? new Date(row.created_at).toLocaleDateString() : "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex items-center justify-end gap-1">
                      {DETAIL_MODE_STATES.has(row.state) && (
                        <Link
                          to="/settings/tools?section=sources"
                          className="rounded p-1 text-slate-400 hover:text-slate-700"
                          title={t("mappingsConsole.triage.detailMode")}
                          aria-label={t("mappingsConsole.triage.detailMode")}
                          data-testid={`mappings-detail-mode-${row.ref}`}
                        >
                          <ExternalLink className="size-4" />
                        </Link>
                      )}
                      <Link
                        to={`/postings/${row.ref}`}
                        className="rounded p-1 text-slate-400 hover:text-slate-700"
                        title={t("mappingsConsole.triage.openPosting")}
                        aria-label={t("mappingsConsole.triage.openPosting")}
                      >
                        <MapPin className="size-4" />
                      </Link>
                      <button
                        type="button"
                        className="rounded p-1 text-slate-400 hover:text-slate-700"
                        title={t("mappingsConsole.triage.trace")}
                        aria-label={t("mappingsConsole.triage.trace")}
                        onClick={() => setTraceId(row.id)}
                        data-testid={`mappings-trace-${row.ref}`}
                      >
                        <Eye className="size-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {queue?.next_cursor && (
        <div className="flex justify-center">
          <Button
            variant="outline"
            size="sm"
            disabled={loading}
            onClick={() => void load({ ...filters, cursor: queue.next_cursor }, true)}
            data-testid="mappings-load-more"
          >
            <ChevronDown className="mr-1 size-4" />
            {t("mappingsConsole.triage.loadMore")}
          </Button>
        </div>
      )}

      {traceId && (
        <EntityDetailsDrawer
          testid="mappings-trace-drawer"
          title={trace?.posting.title ?? t("mappingsConsole.triage.trace")}
          headerBadge={trace?.posting.ref}
          onClose={() => setTraceId(null)}
          actions={
            trace?.review_row && trace.review_row.status === "pending"
              ? [
                  {
                    label: t("mappingsConsole.quality.markCorrect"),
                    onClick: () => {
                      void resolveTrace(true);
                    },
                    testid: "mappings-trace-correct",
                  },
                  {
                    label: t("mappingsConsole.quality.markWrong"),
                    onClick: () => {
                      void resolveTrace(false);
                    },
                    variant: "destructive" as const,
                    testid: "mappings-trace-wrong",
                  },
                ]
              : trace?.review_row
                ? [
                    {
                      label: t(
                        `mappingsConsole.quality.status.${trace.review_row.status}`,
                      ),
                      onClick: () => {},
                      disabled: true,
                    },
                  ]
                : [
                    {
                      label: t("mappingsConsole.quality.addGolden"),
                      onClick: () => {
                        void goldenFromTrace();
                      },
                      testid: "mappings-trace-golden",
                    },
                  ]
          }
        >
          {traceLoading || !trace ? (
            <div className="flex justify-center py-8">
              <Spinner className="h-6 w-6 text-slate-400" />
            </div>
          ) : (
            <div className="space-y-3 text-sm" data-testid="mappings-trace-body">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={STATE_TONE[trace.posting.state] ?? "secondary"}>
                  {t(`mappingsConsole.state.${trace.posting.state}`)}
                </Badge>
                {trace.outcome.method && <Badge variant="secondary">{trace.outcome.method}</Badge>}
                {trace.outcome.confidence != null && (
                  <span className="text-slate-500">
                    {t("mappingsConsole.triage.confidence", {
                      value: (trace.outcome.confidence * 100).toFixed(0),
                    })}
                  </span>
                )}
              </div>
              {trace.outcome.reason_prose && (
                <p className="text-slate-600">{trace.outcome.reason_prose}</p>
              )}
              {trace.review && (
                <p className="text-slate-600">
                  {t("mappingsConsole.triage.reviewLine", {
                    reason: t(`mappingsConsole.reviewReason.${trace.review.reason}`),
                  })}
                  {trace.review.note ? ` — ${trace.review.note}` : ""}
                </p>
              )}
              {trace.features.candidates.length > 0 && (
                <div>
                  <p className="mb-1 font-medium text-slate-700">
                    {t("mappingsConsole.triage.candidates")}
                  </p>
                  <ul className="space-y-1">
                    {trace.features.candidates.slice(0, 5).map((candidate) => (
                      <li key={candidate.job_id} className="text-slate-600">
                        <span className="font-mono text-xs">{candidate.job_code}</span>{" "}
                        {candidate.deterministic ?? "—"}
                        {candidate.shared_skills.length > 0 && (
                          <span className="text-xs text-slate-400">
                            {" "}
                            · {candidate.shared_skills.slice(0, 4).join(", ")}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {trace.features.degraded && (
                <p className="text-amber-700">
                  {t("mappingsConsole.triage.degraded", { reason: trace.features.degraded })}
                </p>
              )}
              {!trace.posting.catalog_job_id && (
                <div className="space-y-1.5 rounded-lg border p-2.5">
                  <p className="text-xs font-medium text-slate-700">
                    {t("mappingsConsole.triage.pickerTitle")}
                  </p>
                  <JobTypePicker
                    value={mapJobId}
                    onChange={setMapJobId}
                    candidates={trace.features.candidates}
                    disabled={busy}
                  />
                  <Button
                    size="sm"
                    disabled={busy || !mapJobId}
                    onClick={() => mapJobId && void mapTrace(mapJobId)}
                    data-testid="mappings-map-selected"
                  >
                    {t("mappingsConsole.triage.mapAction")}
                  </Button>
                </div>
              )}
              <div>
                <p className="mb-1 font-medium text-slate-700">
                  {t("mappingsConsole.triage.journal")}
                </p>
                <ul className="space-y-1 text-xs text-slate-500">
                  {trace.journal.slice(0, 6).map((entry) => (
                    <li key={entry.id}>
                      {entry.created_at
                        ? new Date(entry.created_at).toLocaleString()
                        : "—"}{" "}
                      · {entry.actor_kind}
                    </li>
                  ))}
                </ul>
              </div>
              {trace.proposal && (
                <p className="text-slate-600">
                  {t("mappingsConsole.triage.proposalLink")}{" "}
                  <Link className="underline" to="/settings/taxonomy?tab=enrichment">
                    {t("mappingsConsole.triage.proposalQueue")}
                  </Link>
                </p>
              )}
            </div>
          )}
        </EntityDetailsDrawer>
      )}
    </div>
  );
}
