import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";
import { compareJobs } from "@/api/matching";
import { ScoreRing } from "@/components/ScoreRing";
import { DemandBadge } from "@/components/DemandBadge";
import { educationChipLabel } from "@/components/JobCard";
import { EmptyState } from "@/components/ui";
import { dimensionKeys, dimensionKey } from "@/lib/fitDimensions";
import type { FitDimension, RankedJob } from "@/types";

function formatSalary(job: RankedJob): string {
  const median = job.job.attributes?.salary?.median;
  if (!median) return "—";
  const currency = job.job.attributes?.salary?.currency ?? "";
  return `${median[0].toLocaleString()}–${median[1].toLocaleString()} ${currency}`.trim();
}

function environments(job: RankedJob): string {
  const list = job.job.attributes?.environments ?? [];
  return list.length > 0 ? list.map((e) => String(e).replace(/_/g, " ")).join(", ") : "—";
}

function FitCell({
  entry,
  best,
  testId,
}: {
  entry: FitDimension;
  best: boolean;
  testId: string;
}) {
  return (
    <div
      className={`flex items-center gap-2 rounded-lg px-2 py-1 ${best ? "bg-emerald-50" : ""}`}
      data-testid={testId}
      data-best={best ? "true" : "false"}
    >
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
        <div
          className={`h-1.5 rounded-full ${
            entry.score >= 7 ? "bg-emerald-500" : entry.score >= 4 ? "bg-amber-500" : "bg-rose-400"
          }`}
          style={{ width: `${(entry.score / 10) * 100}%` }}
        />
      </div>
      <span className={`w-8 text-right text-xs ${best ? "font-semibold text-emerald-700" : "text-slate-400"}`}>
        {Number(entry.score).toFixed(1)}
      </span>
    </div>
  );
}

export function Compare() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const ids = useMemo(
    () => [...new Set((params.get("jobs") ?? "").split(",").map((s) => s.trim()).filter(Boolean))],
    [params]
  );
  const [rows, setRows] = useState<RankedJob[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = ids.join(",");

  useEffect(() => {
    if (ids.length < 2 || ids.length > 4) {
      setError(t("compare.emptyBodyShort"));
      setRows(null);
      return;
    }
    setError(null);
    setRows(null);
    compareJobs(ids)
      .then(setRows)
      .catch(() => setError("Couldn't load the comparison — one of the jobs may not exist."));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (error) {
    return (
      <div className="space-y-4" data-testid="compare-page">
        <h1 className="text-2xl font-bold text-slate-900">{t("compare.title")}</h1>
        <EmptyState title={t("compare.emptyTitle")} description={error} />
      </div>
    );
  }

  if (!rows) {
    return (
      <div className="space-y-4" data-testid="compare-page">
        <h1 className="text-2xl font-bold text-slate-900">{t("compare.title")}</h1>
        <div className="h-40 animate-pulse rounded-xl bg-slate-100" />
      </div>
    );
  }

  const dims = dimensionKeys(rows.map((r) => r.breakdown));
  const bestOverall = Math.max(...rows.map((r) => r.fit_score));
  const gridCols = `140px repeat(${rows.length}, minmax(0, 1fr))`;

  return (
    <div className="space-y-4" data-testid="compare-page">
      <h1 className="text-2xl font-bold text-slate-900">{t("compare.title")}</h1>
      <p className="text-sm text-slate-500">{t("compare.hint")}</p>
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white" data-testid="compare-table">
        <div className="min-w-[640px]">
          <div className="grid gap-3 border-b border-slate-100 p-4" style={{ gridTemplateColumns: gridCols }}>
            <div />
            {rows.map((r) => (
              <div key={r.job.id} className="flex items-center gap-3" data-testid={`compare-col-${r.job.id}`}>
                <ScoreRing score={r.score} size={44} />
                <div className="min-w-0">
                  <Link
                    to={`/jobs/${r.job.code}`}
                    className="block truncate font-medium text-slate-900 hover:text-primary-700"
                  >
                    {r.job.title}
                  </Link>
                  <span className="text-xs text-slate-400">
                    fit {Number(r.fit_score).toFixed(1)} · you {r.user_score ?? "–"}
                  </span>
                  {r.gated && r.gate_reasons.length > 0 && (
                    <span className="mt-1 block w-fit rounded-full bg-rose-100 px-2 py-0.5 text-xs text-rose-700">
                      {r.gate_reasons.join(", ")}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="grid gap-3 border-b border-slate-100 p-4" style={{ gridTemplateColumns: gridCols }}>
            <span className="self-center text-xs font-medium uppercase text-slate-400">{t("compare.overallFit")}</span>
            {rows.map((r) => (
              <span
                key={r.job.id}
                className={`self-center text-lg font-semibold ${
                  r.fit_score === bestOverall ? "text-emerald-700" : "text-slate-600"
                }`}
                data-testid={`compare-overall-${r.job.id}`}
                data-best={r.fit_score === bestOverall ? "true" : "false"}
              >
                {Number(r.fit_score).toFixed(1)}
              </span>
            ))}
          </div>

          {dims.map((dim) => {
            const entries = rows.map((r) => r.breakdown?.dimensions?.[dim]);
            const scores = entries.filter((e): e is FitDimension => Boolean(e)).map((e) => e.score);
            const best = scores.length > 0 ? Math.max(...scores) : null;
            return (
              <div
                key={dim}
                className="grid items-center gap-3 border-b border-slate-100 p-4"
                style={{ gridTemplateColumns: gridCols }}
                data-testid={`compare-dim-row-${dim}`}
              >
                <span className="text-xs font-medium uppercase text-slate-400">
                  {t(dimensionKey(dim), { defaultValue: dim })}
                </span>
                {entries.map((entry, i) =>
                  entry ? (
                    <FitCell
                      key={rows[i].job.id}
                      entry={entry}
                      best={best !== null && entry.score === best}
                      testId={`compare-cell-${dim}-${rows[i].job.id}`}
                    />
                  ) : (
                    <span key={rows[i].job.id} className="text-xs text-slate-300">
                      —
                    </span>
                  )
                )}
              </div>
            );
          })}

          {[
            {
              label: t("compare.demand"),
              cells: rows.map((r) => <DemandBadge key={r.job.id} outlook={r.job.attributes?.demand?.outlook} />),
            },
            {
              label: t("compare.education"),
              cells: rows.map((r) => {
                const level = r.job.attributes?.education?.level;
                return (
                  <span key={r.job.id} className="text-xs text-slate-600">
                    {level ? educationChipLabel(t, level) : "—"}
                  </span>
                );
              }),
            },
            {
              label: t("compare.salaryMedian"),
              cells: rows.map((r) => (
                <span key={r.job.id} className="text-xs text-slate-600">
                  {formatSalary(r)}
                </span>
              )),
            },
            {
              label: t("compare.environments"),
              cells: rows.map((r) => (
                <span key={r.job.id} className="text-xs text-slate-600">
                  {environments(r)}
                </span>
              )),
            },
          ].map((row) => (
            <div key={row.label} className="grid items-center gap-3 border-b border-slate-100 p-4" style={{ gridTemplateColumns: gridCols }}>
              <span className="text-xs font-medium uppercase text-slate-400">{row.label}</span>
              {row.cells}
            </div>
          ))}

          <div className="grid gap-3 p-4" style={{ gridTemplateColumns: gridCols }}>
            <span className="self-center text-xs font-medium uppercase text-slate-400">AI notes</span>
            {rows.map((r) => (
              <details key={r.job.id} data-testid={`compare-ai-${r.job.id}`}>
                <summary className="cursor-pointer text-xs text-primary-700">
                  {r.insight?.ai_score != null ? t("compare.aiScore", { score: Number(r.insight.ai_score).toFixed(1) }) : t("compare.notScored")}
                </summary>
                <div className="mt-2 space-y-2 text-xs text-slate-600">
                  {(r.insight?.ai_positives ?? []).slice(0, 3).map((p, i) => (
                    <p key={`pos-${i}`}>+ {p.title}{p.detail ? `: ${p.detail}` : ""}</p>
                  ))}
                  {(r.insight?.ai_negatives ?? []).slice(0, 3).map((n, i) => (
                    <p key={`neg-${i}`}>− {n.title}{n.detail ? `: ${n.detail}` : ""}</p>
                  ))}
                  {r.insight?.ai_score == null && <p>{t("compare.scoreToUnlock")}</p>}
                </div>
              </details>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
