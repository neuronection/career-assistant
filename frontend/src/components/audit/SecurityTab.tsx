import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchAuditEvents, type AuditEventRow, type AuditWindow } from "@/api/audit";
import { apiDetail } from "@/api/client";
import { EmptyState, Spinner } from "@/components/ui";

const PAGE_SIZE = 50;

const selectClass =
  "rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-3 py-2 text-sm text-[var(--as-fg)]";

interface Filters {
  group: "" | "auth" | "admin";
  outcome: string;
  actor: string;
  window: AuditWindow;
}

const DEFAULT_FILTERS: Filters = { group: "", outcome: "", actor: "", window: "7d" };

/** The security & access tab: the identity ``audit_events`` trail
 * (logins, denials, admin acts) — its first read surface (plan 151 D5). */
export function SecurityTab() {
  const { t } = useTranslation();
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [rows, setRows] = useState<AuditEventRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(
    async (current: Filters, currentPage: number) => {
      setLoading(true);
      setError("");
      try {
        const result = await fetchAuditEvents({
          group: current.group || "all",
          outcome: current.outcome || undefined,
          actor: current.actor || undefined,
          window: current.window,
          limit: PAGE_SIZE,
          offset: currentPage * PAGE_SIZE,
        });
        setRows(result.items);
        setTotal(result.total);
      } catch (err) {
        setError(apiDetail(err));
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load(filters, page);
  }, [load, filters, page]);

  const patch = (part: Partial<Filters>) => {
    setFilters({ ...filters, ...part });
    setPage(0);
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
        <select
          aria-label={t("audit.ai.windowFilter")}
          className={selectClass}
          value={filters.window}
          onChange={(e) => patch({ window: e.target.value as AuditWindow })}
        >
          <option value="24h">{t("audit.window.24h")}</option>
          <option value="7d">{t("audit.window.7d")}</option>
          <option value="30d">{t("audit.window.30d")}</option>
        </select>
        <form
          className="min-w-[12rem] flex-1"
          onSubmit={(e) => {
            e.preventDefault();
            patch({ actor: filters.actor });
          }}
        >
          <input
            aria-label={t("audit.security.actorFilter")}
            className={`${selectClass} w-full`}
            placeholder={t("audit.security.actorPlaceholder")}
            value={filters.actor}
            onChange={(e) => setFilters({ ...filters, actor: e.target.value })}
            data-testid="audit-filter-actor"
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
