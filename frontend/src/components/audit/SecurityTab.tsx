import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  exportAuditCsv,
  fetchAuditEvents,
  type AuditEventRow,
  type AuditRangeQuery,
} from "@/api/audit";
import { apiDetail } from "@/api/client";
import { EmptyState, Spinner } from "@/components/ui";
import { downloadCsv } from "@/components/audit/download";

const PAGE_SIZE = 50;

const selectClass =
  "rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-3 py-2 text-sm text-[var(--as-fg)]";

interface Filters {
  group: "" | "auth" | "admin";
  outcome: string;
  actor: string;
}

const DEFAULT_FILTERS: Filters = { group: "", outcome: "", actor: "" };

/** The security & access tab: the identity ``audit_events`` trail
 * (logins, denials, admin acts) — its first read surface (plan 151 D5).
 * The time range is the page-level control, shared with Overview. */
export function SecurityTab({ range }: { range: AuditRangeQuery }) {
  const { t } = useTranslation();
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [actorDraft, setActorDraft] = useState("");
  const [rows, setRows] = useState<AuditEventRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);
  const requestId = useRef(0);

  const load = useCallback(
    async (current: Filters, currentRange: AuditRangeQuery, currentPage: number) => {
      const id = ++requestId.current;
      setLoading(true);
      setError("");
      try {
        const result = await fetchAuditEvents({
          group: current.group || "all",
          outcome: current.outcome || undefined,
          actor: current.actor || undefined,
          ...currentRange,
          limit: PAGE_SIZE,
          offset: currentPage * PAGE_SIZE,
        });
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
    void load(filters, range, page);
  }, [load, filters, range, page]);

  const patch = (part: Partial<Filters>) => {
    setFilters({ ...filters, ...part });
    setActorDraft(part.actor ?? actorDraft);
    setPage(0);
  };

  const exportCsv = async () => {
    setExporting(true);
    try {
      downloadCsv(
        await exportAuditCsv("events", {
          window: range.window,
          from: range.from,
          to: range.to,
          group: filters.group || "all",
          outcome: filters.outcome || undefined,
          actor: filters.actor || undefined,
        }),
        "events",
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
    <div className="space-y-3" data-testid="audit-security-tab">
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={t("audit.security.groupFilter")}
          className={selectClass}
          value={filters.group}
          onChange={(e) => patch({ group: e.target.value as Filters["group"] })}
        >
          <option value="">{t("audit.security.allGroups")}</option>
          <option value="auth">{t("audit.security.group.auth")}</option>
          <option value="admin">{t("audit.security.group.admin")}</option>
        </select>
        <select
          aria-label={t("audit.security.outcomeFilter")}
          className={selectClass}
          value={filters.outcome}
          onChange={(e) => patch({ outcome: e.target.value })}
        >
          <option value="">{t("audit.security.allOutcomes")}</option>
          <option value="ok">{t("audit.security.outcome.ok")}</option>
          <option value="denied">{t("audit.security.outcome.denied")}</option>
          <option value="reuse-denied">
            {t("audit.security.outcome.reuseDenied")}
          </option>
          <option value="coerced">{t("audit.security.outcome.coerced")}</option>
        </select>
        <form
          className="min-w-[12rem] flex-1"
          onSubmit={(e) => {
            e.preventDefault();
            patch({ actor: actorDraft });
          }}
        >
          <input
            aria-label={t("audit.security.actorFilter")}
            className={`${selectClass} w-full`}
            placeholder={t("audit.security.actorPlaceholder")}
            value={actorDraft}
            onChange={(e) => setActorDraft(e.target.value)}
            data-testid="audit-filter-actor"
          />
        </form>
        <button
          type="button"
          className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm disabled:opacity-40"
          disabled={exporting}
          onClick={() => void exportCsv()}
          data-testid="audit-events-export"
        >
          {exporting ? t("audit.export.exporting") : t("audit.export.csv")}
        </button>
      </div>

      {error && <p className="text-sm text-rose-600">{error}</p>}

      {loading ? (
        <div className="flex w-full flex-col items-center justify-center py-24">
          <Spinner size="lg" />
          <p className="mt-3 text-sm text-[var(--as-muted-fg)]">{t("common.loading")}</p>
        </div>
      ) : rows.length === 0 ? (
        <EmptyState title={t("audit.security.empty")} />
      ) : (
        <div className="overflow-x-auto rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--as-border)] text-left text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
                <th className="px-3 py-2">{t("audit.security.colAction")}</th>
                <th className="px-3 py-2">{t("audit.security.colActor")}</th>
                <th className="px-3 py-2">{t("audit.security.colOutcome")}</th>
                <th className="px-3 py-2">{t("audit.security.colResource")}</th>
                <th className="px-3 py-2">{t("audit.ai.colWhen")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.id}
                  className="border-b border-[var(--as-border)]"
                  data-testid="audit-event-row"
                >
                  <td className="px-3 py-2 font-medium text-[var(--as-fg)]">{row.action}</td>
                  <td className="px-3 py-2 text-xs text-[var(--as-muted-fg)]">
                    {row.actor_email ?? row.actor}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`text-xs font-semibold ${
                        row.outcome === "ok" ? "text-emerald-600" : "text-rose-600"
                      }`}
                    >
                      {t(`audit.security.outcome.${row.outcome}`, {
                        defaultValue: row.outcome,
                      })}
                    </span>
                  </td>
                  <td className="max-w-[16rem] truncate px-3 py-2 text-xs text-[var(--as-muted-fg)]">
                    {row.resource || "—"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-[var(--as-muted-fg)]">
                    {new Date(row.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between text-xs text-[var(--as-muted-fg)]">
        <span data-testid="audit-event-range">
          {t("audit.ai.range", { from, to, total: total.toLocaleString() })}
        </span>
        <span className="flex items-center gap-2">
          <button
            type="button"
            className="rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 disabled:opacity-40"
            disabled={page === 0}
            onClick={() => setPage(page - 1)}
            data-testid="audit-event-prev"
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
            data-testid="audit-event-next"
          >
            {t("audit.next")} ›
          </button>
        </span>
      </div>
    </div>
  );
}
