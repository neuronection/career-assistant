import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  exportAuditCsv,
  fetchAuditChanges,
  type AuditChangeRow,
} from "@/api/audit";
import { api, apiDetail } from "@/api/client";
import { EmptyState, SegmentedTabs, Spinner } from "@/components/ui";
import { RangeFilter, rangeParams, type RangeValue } from "@/components/audit/RangeFilter";
import { downloadCsv } from "@/components/audit/download";

const PAGE_SIZE = 50;

const selectClass =
  "rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-3 py-2 text-sm text-[var(--as-fg)]";

export type ChangeEntity = "postings" | "skills";

const POSTING_ACTORS = ["sync_run", "extract_llm", "detail_fetch", "company_match", "retag", "manual", "expiry"] as const;
const SKILL_ACTORS = ["admin", "system", "sync", "job", "user"] as const;
const POSTING_OUTCOMES = ["ok", "partial", "error"] as const;
const SKILL_EVENTS = ["created", "updated", "promoted", "auto_promoted", "deprecated", "restored", "merged", "deleted"] as const;

function outcomeClass(value: string): string {
  if (value === "error") return "text-rose-600";
  if (value === "partial" || value === "merged" || value === "deprecated") return "text-amber-600";
  return "text-emerald-600";
}

function ChangeDetail({ row, entity }: { row: AuditChangeRow; entity: ChangeEntity }) {
  const { t } = useTranslation();
  const payload = entity === "postings" ? row.diff : row.detail;
  const [remapNote, setRemapNote] = useState("");
  const [remapping, setRemapping] = useState(false);
  const remap = async () => {
    if (row.posting_id == null) return;
    setRemapping(true);
    try {
      await api.post(`/admin/postings/${row.posting_id}/remap`);
      setRemapNote(t("audit.changes.remapDone"));
    } catch {
      setRemapNote(t("audit.changes.remapFailed"));
    } finally {
      setRemapping(false);
    }
  };
  return (
    <div
      className="mx-2 mb-2 rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-muted)] p-3 text-xs"
      data-testid={`audit-change-detail-${row.id}`}
    >
      {entity === "postings" && row.actor_kind === "retag" && row.posting_id != null && (
        <div className="mb-2 flex items-center gap-2">
          <button
            onClick={() => void remap()}
            disabled={remapping}
            className="rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-0.5 text-[11px] text-[var(--as-fg)] hover:underline disabled:opacity-50"
            data-testid={`audit-change-remap-${row.id}`}
          >
            {t("audit.changes.remap")}
          </button>
          <span className="text-[10px] text-[var(--as-muted-fg)]">
            {t("audit.changes.remapHint")}
          </span>
          {remapNote && <span className="text-[10px] text-emerald-700">{remapNote}</span>}
        </div>
      )}
      {row.actor_ref && Object.keys(row.actor_ref).length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {Object.entries(row.actor_ref).map(([key, value]) => (
            <span
              key={key}
              className="rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-0.5"
            >
              {key}: <span className="font-medium">{String(value).slice(0, 24)}</span>
            </span>
          ))}
        </div>
      )}
      {row.operation && (
        <p className="mb-2 break-all text-[var(--as-muted-fg)]">
          {t("audit.changes.operationLabel")}
          {JSON.stringify(row.operation)}
        </p>
      )}
      {payload ? (
        <pre className="max-h-60 overflow-y-auto whitespace-pre-wrap break-all rounded-[var(--as-radius)] bg-[var(--as-surface)] p-2 text-[11px]">
          {JSON.stringify(payload, null, 2)}
        </pre>
      ) : (
        <p className="text-[var(--as-muted-fg)]">{t("audit.changes.noDiff")}</p>
      )}
    </div>
  );
}

/** The data changes tab (plan 152): the posting and skill journals as one
 * cross-entity "who changed what" view with actor and outcome filters. */
export function ChangesTab() {
  const { t } = useTranslation();
  const [entity, setEntity] = useState<ChangeEntity>("postings");
  const [actorKind, setActorKind] = useState("");
  const [result, setResult] = useState("");
  const [range, setRange] = useState<RangeValue>({ window: "7d", from: "", to: "" });
  const [rows, setRows] = useState<AuditChangeRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const requestId = useRef(0);

  const load = useCallback(
    async (
      currentEntity: ChangeEntity,
      currentActor: string,
      currentResult: string,
      currentRange: RangeValue,
      currentPage: number,
    ) => {
      const id = ++requestId.current;
      setLoading(true);
      setError("");
      try {
        const params: Record<string, unknown> = {
          entity: currentEntity,
          ...rangeParams(currentRange),
          limit: PAGE_SIZE,
          offset: currentPage * PAGE_SIZE,
        };
        if (currentActor) params.actor_kind = currentActor;
        if (currentResult) {
          if (currentEntity === "postings") params.outcome = currentResult;
          else params.event = currentResult;
        }
        const response = await fetchAuditChanges(params as Parameters<typeof fetchAuditChanges>[0]);
        if (id !== requestId.current) return;
        setRows(response.items);
        setTotal(response.total);
      } catch (err) {
        if (id === requestId.current) setError(apiDetail(err));
      } finally {
        if (id === requestId.current) setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load(entity, actorKind, result, range, page);
  }, [load, entity, actorKind, result, range, page]);

  const switchEntity = (next: ChangeEntity) => {
    setEntity(next);
    setActorKind("");
    setResult("");
    setPage(0);
    setExpanded(null);
  };

  const actors = entity === "postings" ? POSTING_ACTORS : SKILL_ACTORS;
  const results = entity === "postings" ? POSTING_OUTCOMES : SKILL_EVENTS;

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const from = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const to = Math.min(total, (page + 1) * PAGE_SIZE);

  return (
    <div className="space-y-3" data-testid="audit-changes-tab">
      <div className="flex flex-wrap items-center gap-2">
        <SegmentedTabs
          ariaLabel={t("audit.changes.entityAria")}
          items={[
            { value: "postings", label: t("audit.changes.entity.postings") },
            { value: "skills", label: t("audit.changes.entity.skills") },
          ]}
          value={entity}
          onValueChange={(next) => switchEntity(next as ChangeEntity)}
        />
        <select
          aria-label={t("audit.changes.actorFilter")}
          className={selectClass}
          value={actorKind}
          onChange={(e) => {
            setActorKind(e.target.value);
            setPage(0);
          }}
        >
          <option value="">{t("audit.changes.allActors")}</option>
          {actors.map((value) => (
            <option key={value} value={value}>
              {t(`audit.changes.actor.${value}`, { defaultValue: value.replace(/_/g, " ") })}
            </option>
          ))}
        </select>
        <select
          aria-label={t("audit.changes.resultFilter")}
          className={selectClass}
          value={result}
          onChange={(e) => {
            setResult(e.target.value);
            setPage(0);
          }}
        >
          <option value="">
            {entity === "postings"
              ? t("audit.changes.allOutcomes")
              : t("audit.changes.allEvents")}
          </option>
          {results.map((value) => (
            <option key={value} value={value}>
              {t(`audit.changes.result.${value}`, { defaultValue: value.replace(/_/g, " ") })}
            </option>
          ))}
        </select>
        <RangeFilter
          value={range}
          onChange={(next) => {
            setRange(next);
            setPage(0);
          }}
          allowAllTime
        />
        <button
          type="button"
          className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm disabled:opacity-40"
          onClick={() =>
            void (async () => {
              try {
                downloadCsv(
                  await exportAuditCsv("changes", {
                    ...rangeParams(range),
                    entity,
                    actor_kind: actorKind || undefined,
                    outcome: entity === "postings" && result ? result : undefined,
                    event: entity === "skills" && result ? result : undefined,
                  }),
                  `changes_${entity}`,
                );
              } catch (err) {
                setError(apiDetail(err));
              }
            })()
          }
          data-testid="audit-changes-export"
        >
          {t("audit.export.csv")}
        </button>
      </div>

      {error && <p className="text-sm text-rose-600">{error}</p>}

      {loading ? (
        <div className="flex w-full flex-col items-center justify-center py-24">
          <Spinner size="lg" />
          <p className="mt-3 text-sm text-[var(--as-muted-fg)]">{t("common.loading")}</p>
        </div>
      ) : rows.length === 0 ? (
        <EmptyState title={t("audit.changes.empty")} />
      ) : (
        <div className="overflow-x-auto rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--as-border)] text-left text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
                <th className="px-3 py-2">
                  {entity === "postings"
                    ? t("audit.changes.colOutcome")
                    : t("audit.changes.colEvent")}
                </th>
                <th className="px-3 py-2">{t("audit.changes.colSubject")}</th>
                <th className="px-3 py-2">{t("audit.changes.colActor")}</th>
                <th className="px-3 py-2">{t("audit.ai.colWhen")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const kind = row.outcome ?? row.event ?? "";
                return (
                  <Fragment key={row.id}>
                    <tr
                      className="cursor-pointer border-b border-[var(--as-border)] hover:bg-[var(--as-muted)] focus-visible:bg-[var(--as-muted)] focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--as-accent)]"
                      onClick={() => setExpanded(expanded === row.id ? null : row.id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          setExpanded(expanded === row.id ? null : row.id);
                        }
                      }}
                      tabIndex={0}
                      aria-expanded={expanded === row.id}
                      data-testid="audit-change-row"
                    >
                      <td className={`px-3 py-2 text-xs font-semibold ${outcomeClass(kind)}`}>
                        {t(`audit.changes.result.${kind}`, { defaultValue: kind })}
                        {expanded === row.id ? " ▾" : " ▸"}
                      </td>
                      <td className="px-3 py-2 font-medium text-[var(--as-fg)]">
                        {entity === "postings" ? (
                          <Link
                            to={`/postings/${row.posting_id}`}
                            className="underline-offset-2 hover:underline"
                          >
                            {t("audit.changes.postingRef", {
                              id: (row.posting_id ?? "").slice(0, 8),
                            })}
                          </Link>
                        ) : (
                          row.skill_label
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs text-[var(--as-muted-fg)]">
                        {t(`audit.changes.actor.${row.actor_kind}`, {
                          defaultValue: row.actor_kind.replace(/_/g, " "),
                        })}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-xs text-[var(--as-muted-fg)]">
                        {new Date(row.occurred_at).toLocaleString()}
                      </td>
                    </tr>
                    {expanded === row.id && (
                      <tr>
                        <td colSpan={4} className="p-0">
                          <ChangeDetail row={row} entity={entity} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between text-xs text-[var(--as-muted-fg)]">
        <span data-testid="audit-changes-range">
          {t("audit.ai.range", { from, to, total: total.toLocaleString() })}
        </span>
        <span className="flex items-center gap-2">
          <button
            type="button"
            className="rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 disabled:opacity-40"
            disabled={page === 0}
            onClick={() => setPage(page - 1)}
          >
            ‹ {t("audit.prev")}
          </button>
          <span className="tabular-nums">
            {page + 1} / {pageCount}
          </span>
          <button
            type="button"
            className="rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 disabled:opacity-40"
            disabled={page + 1 >= pageCount}
            onClick={() => setPage(page + 1)}
          >
            {t("audit.next")} ›
          </button>
        </span>
      </div>
    </div>
  );
}
