import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui";
import { ScoreBubble } from "@/components/score/ScoreBubble";
import {
  ScoreBreakdown,
  type BreakdownDimension,
} from "@/components/score/ScoreBreakdown";
import type { PostingDetailOut } from "@/types/wire";

const GATE_LABEL_KEYS: Record<string, string> = {
  travel: "postingDetail.gate.travel",
  shift: "postingDetail.gate.shift",
  hours: "postingDetail.gate.hours",
  salary_min: "postingDetail.gate.salaryMin",
};

type Match = NonNullable<PostingDetailOut["match"]>;

export function matchDimensions(
  match: Match,
  t: (key: string, opts?: Record<string, unknown>) => string
): BreakdownDimension[] {
  return Object.entries(match.breakdown ?? {}).map(([dim, entry]) => ({
    key: dim,
    label: t(`dimensions.${dim}`, { defaultValue: dim.replace(/_/g, " ") }),
    score: entry.score,
    weight: entry.weight,
    detail: entry.detail,
    neutral: Boolean(entry.neutral),
  }));
}

export function MatchCard({ match }: { match: Match }) {
  const { t } = useTranslation();
  const dimensions = matchDimensions(match, t);
  return (
    <section
      className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
      data-testid="match-card"
    >
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase text-[var(--as-muted-fg)]">
          {t("postingDetail.matchScore")}
        </h3>
        <div className="flex items-center gap-1.5">
          <ScoreBubble score={match.score} size={44} testId="match-score" />
          <span className="text-[10px] text-[var(--as-muted-fg)]">/10</span>
        </div>
      </div>
      {match.estimate ? (
        <p
          className="mt-1 text-[11px] text-[var(--as-warning)]"
          data-testid="match-estimate-note"
        >
          {t("postingDetail.estimateNote")}
        </p>
      ) : null}
      {match.gates && match.gates.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5" data-testid="posting-gates">
          {match.gates.map((gate) => (
            <Badge key={gate} variant="warning" title={t("postingDetail.gateTitle")}>
              {GATE_LABEL_KEYS[gate] ? t(GATE_LABEL_KEYS[gate]) : gate}
            </Badge>
          ))}
        </div>
      ) : null}
      <ScoreBreakdown
        className="mt-2"
        dimensions={dimensions}
        tone="neutral"
        alwaysShowWeight
        showDetails
        detailsLayout="lines"
        detailsTestId="match-detail-lines"
        labelWidth="7rem"
      />
    </section>
  );
}
