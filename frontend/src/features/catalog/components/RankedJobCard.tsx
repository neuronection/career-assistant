import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui";
import { ItemCardShell } from "@/components/cards/ItemCardShell";
import { ScoreBubble } from "@/components/score/ScoreBubble";
import { ScoreBreakdown, type BreakdownDimension } from "@/components/score/ScoreBreakdown";
import { DemandBadge } from "@/features/postings/components/DemandBadge";
import { dimensionKey } from "@/lib/fitDimensions";
import type { FitBreakdown, MatchStatus, RankedJob } from "@/types/wire";

export function rankedDimensions(
  breakdown: FitBreakdown | null | undefined,
  t: (key: string, opts?: Record<string, unknown>) => string
): BreakdownDimension[] {
  return Object.entries(breakdown?.dimensions ?? {}).map(([key, entry]) => ({
    key,
    label: t(dimensionKey(key), { defaultValue: key }),
    score: entry.score,
    weight: entry.weight,
    detail: entry.detail,
  }));
}

export function RankedJobCard({
  item,
  expanded,
  onToggleBreakdown,
  onRate,
  compareSelected,
  onToggleCompare,
}: {
  item: RankedJob;
  expanded: boolean;
  onToggleBreakdown: () => void;
  onRate: (status: MatchStatus) => void;
  compareSelected: boolean;
  onToggleCompare: () => void;
}) {
  const { t } = useTranslation();
  const job = item.job;
  const dimensions = rankedDimensions(item.breakdown, t);

  return (
    <ItemCardShell
      testId={`ranked-job-${job.code}`}
      actions={
        <div className="flex flex-col gap-1">
          {(["interested", "dismissed"] as MatchStatus[]).map((status) => (
            <button
              key={status}
              onClick={() => onRate(status)}
              data-active={item.status === status ? "true" : "false"}
              className={`rounded-full border px-2.5 py-1 text-xs ${
                item.status === status
                  ? "border-[var(--as-primary)] bg-[var(--as-primary)] text-[var(--as-primary-fg)]"
                  : "border-[var(--as-border)] text-[var(--as-fg)]"
              }`}
            >
              {status === "interested"
                ? t("rankings.interested")
                : t("rankings.dismiss")}
            </button>
          ))}
          <button
            onClick={onToggleCompare}
            data-active={compareSelected ? "true" : "false"}
            className={`rounded-full border px-2.5 py-1 text-xs ${
              compareSelected
                ? "border-[var(--as-success)] bg-[var(--as-success)] text-[var(--as-success-fg)]"
                : "border-[var(--as-border)] text-[var(--as-muted-fg)]"
            }`}
            data-testid={`compare-add-${job.code}`}
          >
            {compareSelected ? t("rankings.comparing") : t("rankings.compare")}
          </button>
        </div>
      }
    >
      <div className="flex shrink-0 flex-col items-center gap-0.5 pt-0.5" data-capture="fit-bubble">
        <ScoreBubble score={item.score} size={52} />
        <span className="text-[9px] font-semibold uppercase tracking-[0.07em] text-[var(--as-muted-fg)]">
          {t("rankings.match")}
        </span>
      </div>

      <div
        className="flex shrink-0 items-center gap-4 self-stretch border-r border-[var(--as-border)] pr-4"
        data-testid={`scores-${job.code}`}
      >
        <div className="text-center">
          <p className="text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)]">
            {t("rankings.fit")}
          </p>
          <p className="text-sm font-semibold text-[var(--as-fg)]">
            {Number(item.fit_score).toFixed(1)}
          </p>
        </div>
        <div className="text-center">
          <p className="text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)]">
            {t("rankings.aiScore")}
          </p>
          <p className="text-sm font-semibold text-[var(--as-fg)]">
            {item.ai_score != null ? Number(item.ai_score).toFixed(1) : "–"}
          </p>
        </div>
        <div className="text-center">
          <p className="text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)]">
            {t("rankings.yourScore")}
          </p>
          <p className="text-sm font-semibold text-[var(--as-fg)]">
            {item.user_score ?? "–"}
          </p>
        </div>
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Link
            to={`/jobs/${job.code}`}
            className="truncate font-medium text-[var(--as-fg)] hover:text-[var(--as-accent)]"
          >
            {job.title}
          </Link>
          <DemandBadge outlook={job.attributes?.demand?.outlook} />
          {item.specialist_dimension ? (
            <Badge variant="warning">
              {t("rankings.strongIn", {
                dimension: t(dimensionKey(item.specialist_dimension)),
              })}
            </Badge>
          ) : null}
          {item.gated && (item.gate_reasons ?? []).length > 0 ? (
            <Badge variant="danger">{(item.gate_reasons ?? []).join(", ")}</Badge>
          ) : null}
        </div>
        <p className="truncate text-sm text-[var(--as-muted-fg)]">{job.short_description}</p>
        <button
          onClick={onToggleBreakdown}
          className="mt-1 text-xs text-[var(--as-accent)] hover:underline"
          data-testid={`breakdown-toggle-${job.code}`}
        >
          {expanded ? t("rankings.hideBreakdown") : t("rankings.why")}
        </button>
        {expanded ? (
          <ScoreBreakdown
            className="mt-2"
            dimensions={dimensions}
            defaultWeight={3}
            showDetails
            detailsLayout="inline"
            testId="fit-breakdown"
            detailsTestId="fit-breakdown-detail"
          />
        ) : null}
      </div>
    </ItemCardShell>
  );
}
