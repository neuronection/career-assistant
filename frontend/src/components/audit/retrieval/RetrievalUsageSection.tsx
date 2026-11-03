import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  fetchRetrievalUsage,
  type RetrievalUsageResponse,
  type RetrievalWindow,
} from "@/api/retrieval";
import { apiDetail } from "@/api/client";
import { Badge } from "@/components/ui";
import { StatTiles, type StatTile } from "@/components/stats/StatTiles";
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
  formatNumber,
  TOOLS_RETRIEVAL_URL,
} from "@/components/audit/retrieval/retrievalHelpers";

export function RetrievalUsageSection({ window }: { window: RetrievalWindow }) {
  const { t } = useTranslation();
  const [data, setData] = useState<RetrievalUsageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    setLoading(true);
    fetchRetrievalUsage({ window })
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

  const totals = useMemo(() => {
    const rows = data?.usage.rows ?? [];
    return rows.reduce(
      (acc, row) => ({
        calls: acc.calls + row.calls,
        tokensIn: acc.tokensIn + row.tokens_in,
        tokensOut: acc.tokensOut + row.tokens_out,
        reindex: acc.reindex + row.reindex_calls,
      }),
      { calls: 0, tokensIn: 0, tokensOut: 0, reindex: 0 },
    );
  }, [data]);

  if (loading) return <RetrievalLoading />;
  if (error) return <RetrievalError message={error} />;

  const rows = data?.usage.rows ?? [];
  const budget = data?.usage.budget ?? null;
  const budgetShare =
    budget && budget.max_tokens > 0
      ? Math.min(100, (budget.used_tokens / budget.max_tokens) * 100)
      : null;

  const tiles: StatTile[] = [
    {
      label: t("audit.retrieval.usage.calls"),
      value: formatNumber(totals.calls),
      hint: t("audit.retrieval.usage.callsHint", {
        reindex: formatNumber(totals.reindex),
      }),
    },
    {
      label: t("audit.retrieval.usage.tokensIn"),
      value: formatNumber(totals.tokensIn),
      hint: t("audit.retrieval.usage.units"),
    },
    {
      label: t("audit.retrieval.usage.tokensOut"),
      value: formatNumber(totals.tokensOut),
      hint: t("audit.retrieval.usage.units"),
    },
    {
      label: t("audit.retrieval.usage.untagged"),
      value: formatNumber(data?.untagged_calls ?? 0),
      hint: t("audit.retrieval.usage.untaggedHint"),
    },
  ];

  return (
    <div className="space-y-3" data-testid="retrieval-usage">
      <RetrievalSectionHeader
        title={t("audit.retrieval.usage.title")}
        hint={t("audit.retrieval.usage.hint")}
        actions={
          <Link
            to={TOOLS_RETRIEVAL_URL}
            className="text-xs font-semibold text-[var(--as-primary)] hover:underline"
          >
            {t("audit.retrieval.openTools")} →
          </Link>
        }
      />

      {rows.length === 0 ? (
        <div data-testid="retrieval-usage-empty">
          <StateNote>{t("audit.retrieval.usage.empty")}</StateNote>
        </div>
      ) : (
        <>
          <StatTiles tiles={tiles} layout="auto" testId="retrieval-usage-tiles" />
          <div
            className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
            data-testid="retrieval-usage-budget"
          >
            {budget ? (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h4 className="text-xs font-semibold text-[var(--as-fg)]">
                    {t("audit.retrieval.usage.budget", {
                      window: budget.window,
                    })}
                  </h4>
                  {data?.budget?.exhausted ? (
                    <Badge variant="danger">
                      {t("audit.retrieval.usage.budgetExhausted")}
                    </Badge>
                  ) : (
                    <Badge variant="success">
                      {t("audit.retrieval.usage.budgetOk")}
                    </Badge>
                  )}
                </div>
                <p className="mt-1 text-xs text-[var(--as-muted-fg)]">
                  {t("audit.retrieval.usage.budgetUsage", {
                    used: formatNumber(budget.used_tokens),
                    max: formatNumber(budget.max_tokens),
                  })}
                </p>
                {budgetShare != null && (
                  <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-[var(--as-muted)]">
                    <div
                      className={`h-full rounded-full ${
                        budgetShare >= 100 ? "bg-rose-500" : "bg-[var(--as-accent)]"
                      }`}
                      style={{ width: `${budgetShare}%` }}
                    />
                  </div>
                )}
              </>
            ) : (
              <p className="text-xs text-[var(--as-muted-fg)]">
                {t("audit.retrieval.usage.noBudget")}
              </p>
            )}
          </div>

          <div className={tableShellClass}>
            <table className={tableClass}>
              <thead>
                <tr className="border-b border-[var(--as-border)]">
                  <th className={thClass}>{t("audit.retrieval.usage.colDay")}</th>
                  <th className={thClass}>{t("audit.retrieval.usage.colSpace")}</th>
                  <th className={thClass}>{t("audit.retrieval.usage.colKind")}</th>
                  <th className={thClass}>{t("audit.retrieval.usage.colCalls")}</th>
                  <th className={thClass}>{t("audit.retrieval.usage.colTokensIn")}</th>
                  <th className={thClass}>{t("audit.retrieval.usage.colTokensOut")}</th>
                  <th className={thClass}>{t("audit.retrieval.usage.colReindex")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr
                    key={`${row.day}-${row.space_id}-${row.kind}-${index}`}
                    className="border-b border-[var(--as-border)] last:border-b-0"
                    data-testid="retrieval-usage-row"
                  >
                    <td className={`${tdClass} tabular-nums`}>{row.day}</td>
                    <td className={`${tdClass} font-mono text-[11px]`}>
                      {row.space_id.slice(0, 8)}
                    </td>
                    <td className={tdClass}>
                      {t(`retrieval.kind.${row.kind}`, { defaultValue: row.kind })}
                    </td>
                    <td className={`${tdClass} tabular-nums`}>
                      {formatNumber(row.calls)}
                    </td>
                    <td className={`${tdClass} tabular-nums`}>
                      {formatNumber(row.tokens_in)}
                    </td>
                    <td className={`${tdClass} tabular-nums`}>
                      {formatNumber(row.tokens_out)}
                    </td>
                    <td className={`${tdClass} tabular-nums`}>
                      {formatNumber(row.reindex_calls)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data?.groups_truncated && (
            <Badge variant="warning">
              {t("audit.retrieval.usage.groupsTruncated")}
            </Badge>
          )}
        </>
      )}
    </div>
  );
}
