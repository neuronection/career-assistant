import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  exportAuditCsv,
  fetchAuditBreakdown,
  fetchAuditGenerations,
  type AIGenerationRow,
  type AuditBreakdownRow,
} from "@/api/audit";
import { apiDetail } from "@/api/client";
import { EmptyState, Spinner } from "@/components/ui";
import {
  EMPTY_RANGE,
  RangeFilter,
  rangeParams,
  type RangeValue,
} from "@/components/audit/RangeFilter";
import { downloadCsv } from "@/components/audit/download";
import { formatLatency } from "@/config/auditVocab";

const PAGE_SIZE = 50;

const selectClass =
  "rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-3 py-2 text-sm text-[var(--as-fg)]";

interface Filters {
  task: string;
  provider: string;
  status: string;
  tier: string;
  range: RangeValue;
  q: string;
}

const EMPTY_FILTERS: Filters = {
  task: "",
  provider: "",
  status: "",
  tier: "",
  range: EMPTY_RANGE,
  q: "",
};

function GenerationDetail({ row }: { row: AIGenerationRow }) {
  const { t } = useTranslation();
  return (
    <div
      className="mx-2 mb-2 rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-muted)] p-3 text-xs"
      data-testid={`audit-gen-detail-${row.id}`}
    >
      {row.error && <p className="mb-2 font-medium text-rose-600">{row.error}</p>}
      <p className="mb-2 whitespace-pre-wrap break-words text-[var(--as-muted-fg)]">
        {t("audit.ai.promptLabel")}
        {row.prompt ? row.prompt.slice(0, 600) : "—"}
      </p>
      <div className="mb-2 flex flex-wrap gap-1.5">
        {row.run_id && (
          <span className="rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-0.5">
            {t("audit.ai.runChip", { id: row.run_id.slice(0, 8) })}
          </span>
        )}
        {row.run_stage && (
          <span className="rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-0.5">
            {t("audit.ai.stageChip", { stage: row.run_stage })}
          </span>
        )}
        {row.prompt_version && (
          <span className="rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-0.5">
            {t("audit.ai.promptChip", { version: row.prompt_version })}
          </span>
        )}
        {row.pack_key && (
          <span className="rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-0.5">
            {t("audit.ai.packChip", {
              key: row.pack_key,
              version: row.pack_version ?? "?",
            })}
          </span>
        )}
      </div>
      {row.output && (
        <pre className="max-h-60 overflow-auto rounded-[var(--as-radius)] bg-[var(--as-surface)] p-2 text-[11px] leading-relaxed text-[var(--as-fg)]">
          {JSON.stringify(row.output, null, 2)}
        </pre>
      )}
    </div>
  );
}

function GenerationRow({
  row,
  expanded,
  onToggle,
}: {
  row: AIGenerationRow;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  return (
    <>
      <tr
        className="cursor-pointer border-b border-[var(--as-border)] hover:bg-[var(--as-muted)] focus-visible:bg-[var(--as-muted)] focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--as-accent)]"
        onClick={onToggle}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onToggle();
          }
        }}
        tabIndex={0}
        aria-expanded={expanded}
        data-testid={`audit-gen-row-${row.id}`}
      >
        <td className="px-3 py-2">
          <span
            className={`text-xs font-semibold ${
              row.status === "ok" ? "text-emerald-600" : "text-rose-600"
            }`}
          >
            {t(`aiSettings.status.${row.status}`, { defaultValue: row.status })}
            {expanded ? " ▾" : " ▸"}
          </span>
        </td>
        <td className="px-3 py-2 font-medium text-[var(--as-fg)]">
          {t(`aiSettings.task.${row.task_type}`, {
            defaultValue: row.task_type.replace(/_/g, " "),
          })}
          {row.provider === "mock" && (
            <span
              data-testid={`audit-gen-simulated-${row.id}`}
              className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-800"
            >
              {t("audit.ai.simulated")}
            </span>
          )}
        </td>
        <td className="px-3 py-2 text-xs text-[var(--as-muted-fg)]">
          {row.provider}/{row.model}
        </td>
        <td className="px-3 py-2 text-xs tabular-nums text-[var(--as-muted-fg)]">
          {row.tokens_in ?? "?"} → {row.tokens_out ?? "?"}
        </td>
        <td className="px-3 py-2 text-xs tabular-nums text-[var(--as-muted-fg)]">
          {formatLatency(row.latency_ms)}
        </td>
        <td className="px-3 py-2 text-xs text-[var(--as-muted-fg)]">
          {row.task_tier ?? "—"}
        </td>
        <td className="px-3 py-2 text-xs text-[var(--as-muted-fg)]">
          {new Date(row.created_at).toLocaleString()}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={7} className="p-0">
            <GenerationDetail row={row} />
          </td>
        </tr>
      )}
    </>
  );
}

/** The AI ledger tab: facet-driven filters over every AI call, with
 * expandable row detail and lineage chips (run/stage/prompt/pack). */
export function AiActivityTab() {
  const { t } = useTranslation();
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [applied, setApplied] = useState<Filters>(EMPTY_FILTERS);
  const [rows, setRows] = useState<AIGenerationRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [taskFacets, setTaskFacets] = useState<AuditBreakdownRow[]>([]);
  const [providerFacets, setProviderFacets] = useState<AuditBreakdownRow[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    const loadFacets = async () => {
      try {
        const [tasks, providers] = await Promise.all([
          fetchAuditBreakdown("task", { window: "30d", limit: 60 }),
          fetchAuditBreakdown("provider", { window: "30d", limit: 60 }),
        ]);
        setTaskFacets(tasks.rows);
        setProviderFacets(providers.rows);
      } catch {
        setTaskFacets([]);
        setProviderFacets([]);
      }
    };
    void loadFacets();
  }, []);

  const requestId = useRef(0);

  const load = useCallback(
    async (current: Filters, currentPage: number) => {
      const id = ++requestId.current;
      setLoading(true);
      setError("");
      try {
        const params: Record<string, unknown> = {
          limit: PAGE_SIZE,
          offset: currentPage * PAGE_SIZE,
        };
        if (current.task) params.task = current.task;
        if (current.provider) params.provider = current.provider;
        if (current.status) params.status = current.status;
        if (current.tier) params.tier = current.tier;
        Object.assign(params, rangeParams(current.range));
        if (current.q) params.q = current.q;
        const result = await fetchAuditGenerations(params);
        if (id !== requestId.current) return;
        setRows(result.items);
        setTotal(result.total);
      } catch (err) {
        if (id === requestId.current) setError(apiDetail(err));
      } finally {
        if (id === requestId.current) setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load(applied, page);
  }, [load, applied, page]);

  const applyFilters = (next: Filters) => {
    setFilters(next);
    setApplied(next);
    setPage(0);
    setExpanded(null);
  };

  const patch = (part: Partial<Filters>) => applyFilters({ ...filters, ...part });

  const exportCsv = async () => {
    setExporting(true);
    try {
      downloadCsv(
        await exportAuditCsv("ai", {
          ...rangeParams(applied.range),
          task: applied.task || undefined,
          provider: applied.provider || undefined,
          status: applied.status || undefined,
          q: applied.q || undefined,
        }),
        "ai",
      );
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setExporting(false);
    }
  };

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const from = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const to = Math.min(total, (page + 1) * PAGE_SIZE);

  return (
    <div className="space-y-3" data-testid="audit-ai-tab">
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={t("audit.ai.taskFilter")}
          className={selectClass}
          value={filters.task}
          onChange={(e) => patch({ task: e.target.value })}
          data-testid="audit-filter-task"
        >
          <option value="">{t("audit.ai.allTasks")}</option>
          {taskFacets.map((facet) => (
            <option key={facet.key} value={facet.key}>
              {t(`aiSettings.task.${facet.key}`, {
                defaultValue: facet.key.replace(/_/g, " "),
              })}{" "}
              ({facet.calls})
            </option>
          ))}
        </select>
        <select
          aria-label={t("audit.ai.providerFilter")}
          className={selectClass}
          value={filters.provider}
          onChange={(e) => patch({ provider: e.target.value })}
          data-testid="audit-filter-provider"
        >
          <option value="">{t("audit.ai.allProviders")}</option>
          {providerFacets.map((facet) => (
            <option key={facet.key} value={facet.key}>
              {facet.key} ({facet.calls})
            </option>
          ))}
        </select>
        <select
          aria-label={t("audit.ai.statusFilter")}
          className={selectClass}
          value={filters.status}
          onChange={(e) => patch({ status: e.target.value })}
        >
          <option value="">{t("aiSettings.allStatuses")}</option>
          <option value="ok">{t("aiSettings.status.ok")}</option>
          <option value="error">{t("aiSettings.status.error")}</option>
        </select>
        <select
          aria-label={t("audit.ai.tierFilter")}
          className={selectClass}
          value={filters.tier}
          onChange={(e) => patch({ tier: e.target.value })}
        >
          <option value="">{t("audit.ai.anyTier")}</option>
          <option value="fast">{t("audit.ai.tier.fast")}</option>
          <option value="strong">{t("audit.ai.tier.strong")}</option>
        </select>
        <RangeFilter
          value={filters.range}
          onChange={(next) => patch({ range: next })}
          allowAllTime
          testId="audit-gen-range-filter"
        />
        <button
          type="button"
          className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm disabled:opacity-40"
          disabled={exporting}
          onClick={() => void exportCsv()}
          data-testid="audit-gen-export"
        >
          {exporting ? t("audit.export.exporting") : t("audit.export.csv")}
        </button>
        <form
          className="min-w-[12rem] flex-1"
          onSubmit={(e) => {
            e.preventDefault();
            patch({ q: filters.q });
          }}
        >
          <input
            aria-label={t("audit.ai.search")}
            className={`${selectClass} w-full`}
            placeholder={t("audit.ai.searchPlaceholder")}
            value={filters.q}
            onChange={(e) => setFilters({ ...filters, q: e.target.value })}
            data-testid="audit-filter-search"
          />
        </form>
      </div>

      {error && <p className="text-sm text-rose-600">{error}</p>}

      {loading ? (
        <div className="flex w-full flex-col items-center justify-center py-24">
          <Spinner size="lg" />
          <p className="mt-3 text-sm text-[var(--as-muted-fg)]">{t("common.loading")}</p>
        </div>
      ) : rows.length === 0 ? (
        <EmptyState title={t("aiSettings.noGenerations")} />
      ) : (
        <div className="overflow-x-auto rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--as-border)] text-left text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
                <th className="px-3 py-2">{t("audit.ai.colStatus")}</th>
                <th className="px-3 py-2">{t("audit.ai.colTask")}</th>
                <th className="px-3 py-2">{t("audit.ai.colModel")}</th>
                <th className="px-3 py-2">{t("audit.ai.colTokens")}</th>
                <th className="px-3 py-2">{t("audit.ai.colLatency")}</th>
                <th className="px-3 py-2">{t("audit.ai.colTier")}</th>
                <th className="px-3 py-2">{t("audit.ai.colWhen")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <GenerationRow
                  key={row.id}
                  row={row}
                  expanded={expanded === row.id}
                  onToggle={() => setExpanded(expanded === row.id ? null : row.id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between text-xs text-[var(--as-muted-fg)]">
        <span data-testid="audit-gen-range">
          {t("audit.ai.range", { from, to, total: total.toLocaleString() })}
        </span>
        <span className="flex items-center gap-2">
          <button
            type="button"
            className="rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 disabled:opacity-40"
            disabled={page === 0}
            onClick={() => setPage(page - 1)}
            data-testid="audit-gen-prev"
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
            data-testid="audit-gen-next"
          >
            {t("audit.next")} ›
          </button>
        </span>
      </div>
    </div>
  );
}
