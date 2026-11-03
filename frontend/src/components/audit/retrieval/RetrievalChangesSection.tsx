import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { fetchAuditEvents, type AuditEventRow } from "@/api/audit";
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
import {
  parseRetrievalResource,
  retrievalAuditWindow,
  retrievalRunUrl,
  retrievalSpaceUrl,
  shortId,
  TOOLS_RETRIEVAL_URL,
  when,
} from "@/components/audit/retrieval/retrievalHelpers";
import type { RetrievalWindow } from "@/api/retrieval";

const PAGE_SIZE = 50;

export function RetrievalChangesSection({ window }: { window: RetrievalWindow }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<AuditEventRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const auditWindow = retrievalAuditWindow(window);

  useEffect(() => {
    let live = true;
    setLoading(true);
    fetchAuditEvents({
      group: "vector",
      window: auditWindow,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    })
      .then((loaded) => {
        if (!live) return;
        setRows(loaded.items);
        setTotal(loaded.total);
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
  }, [auditWindow, page]);

  useEffect(() => {
    setPage(0);
  }, [auditWindow]);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-3" data-testid="retrieval-changes">
      <RetrievalSectionHeader
        title={t("audit.retrieval.changes.title")}
        hint={t("audit.retrieval.changes.hint")}
        actions={
          <Link
            to={TOOLS_RETRIEVAL_URL}
            className="inline-flex items-center py-1 text-xs font-semibold text-[var(--as-primary)] hover:underline"
          >
            {t("audit.retrieval.openTools")} →
          </Link>
        }
      />

      {window === "90d" && (
        <StateNote>
          {t("audit.retrieval.changes.windowCap", { window: auditWindow })}
        </StateNote>
      )}

      {error && <RetrievalError message={error} />}
      {loading ? (
        <RetrievalLoading />
      ) : rows.length === 0 ? (
        <div data-testid="retrieval-changes-empty">
          <StateNote>{t("audit.retrieval.changes.empty")}</StateNote>
        </div>
      ) : (
        <>
          <div
            className={tableShellClass}
            tabIndex={0}
            role="region"
            aria-label={t("audit.retrieval.changes.title")}
          >
            <table className={tableClass}>
              <thead>
                <tr className="border-b border-[var(--as-border)]">
                  <th className={thClass}>{t("audit.retrieval.changes.colAction")}</th>
                  <th className={thClass}>{t("audit.retrieval.changes.colActor")}</th>
                  <th className={thClass}>{t("audit.retrieval.changes.colResource")}</th>
                  <th className={thClass}>{t("audit.retrieval.changes.colOutcome")}</th>
                  <th className={thClass}>{t("audit.retrieval.changes.colWhen")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <ChangeRow key={row.id} row={row} window={window} />
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between text-xs text-[var(--as-muted-fg)]">
            <span>
              {t("audit.retrieval.changes.range", {
                from: total === 0 ? 0 : page * PAGE_SIZE + 1,
                to: Math.min(total, (page + 1) * PAGE_SIZE),
                total: total.toLocaleString(),
              })}
            </span>
            <span className="flex items-center gap-2">
              <button
                type="button"
                className="rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 disabled:opacity-40"
                disabled={page === 0}
                onClick={() => setPage((current) => Math.max(0, current - 1))}
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
                onClick={() => setPage((current) => current + 1)}
              >
                {t("audit.next")} ›
              </button>
            </span>
          </div>
        </>
      )}
    </div>
  );
}

function ChangeRow({ row, window }: { row: AuditEventRow; window: RetrievalWindow }) {
  const target = parseRetrievalResource(row.resource);
  const link =
    target?.kind === "run"
      ? retrievalRunUrl(target.id, window)
      : target?.kind === "space"
        ? retrievalSpaceUrl(target.id, window)
        : null;
  return (
    <tr
      className="border-b border-[var(--as-border)] last:border-b-0"
      data-testid={`retrieval-change-row-${row.id}`}
    >
      <td className={`${tdClass} font-mono font-medium`}>{row.action}</td>
      <td className={tdClass} title={row.actor}>
        {row.actor_email ?? shortId(row.actor)}
      </td>
      <td className={`${tdClass} font-mono text-[11px]`}>
        {link ? (
          <Link
            to={link}
            className="text-[var(--as-primary)] hover:underline"
            data-testid={`retrieval-change-link-${row.id}`}
          >
            {row.resource}
          </Link>
        ) : (
          row.resource || "—"
        )}
      </td>
      <td className={tdClass}>
        <Badge variant={row.outcome === "ok" ? "success" : "danger"}>
          {row.outcome}
        </Badge>
      </td>
      <td className={`${tdClass} text-[var(--as-muted-fg)]`}>
        {when(row.created_at)}
      </td>
    </tr>
  );
}
