import { useTranslation } from "react-i18next";
import { Percent, TrendingUp, Zap } from "lucide-react";

import type { StatsInsight } from "@/api/stats";

/** The "what changed" strip (H2): deterministic anomaly cards computed
 * server-side. `text_key` maps onto i18n — the wire never carries free
 * text; unknown keys render the neutral card, never raw JSON. */
const INSIGHT_LABELS: Record<string, string> = {
  "insights.volume_high": "marketStats.insights.volumeHigh",
  "insights.volume_low": "marketStats.insights.volumeLow",
  "insights.share_high": "marketStats.insights.shareHigh",
  "insights.share_low": "marketStats.insights.shareLow",
  "insights.skill_lead": "marketStats.insights.skillLead",
};

export function InsightsStrip({ insights }: { insights: StatsInsight[] }) {
  const { t } = useTranslation();
  if (insights.length === 0) return null;
  return (
    <ul
      data-testid="stats-insights"
      className="grid gap-2 md:grid-cols-2 xl:grid-cols-3"
    >
      {insights.map((insight, index) => (
        <li
          key={`${insight.kind}-${insight.subject}-${index}`}
          data-testid="stats-insight-card"
          className="flex items-start gap-2 rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3 text-xs"
        >
          <span className="mt-0.5 shrink-0 text-[var(--as-accent,var(--chart-1,#6172f3))]">
            {insight.kind === "volume" ? (
              <TrendingUp className="size-3.5" aria-hidden />
            ) : insight.kind === "share" ? (
              <Percent className="size-3.5" aria-hidden />
            ) : (
              <Zap className="size-3.5" aria-hidden />
            )}
          </span>
          <span className="text-[var(--as-fg)]">{text(insight, t)}</span>
        </li>
      ))}
    </ul>
  );
}

function text(insight: StatsInsight, t: Translate): string {
  const key = INSIGHT_LABELS[insight.text_key];
  if (!key) {
    return t("marketStats.insights.fallback", { subject: insight.subject });
  }
  const subject =
    insight.kind === "volume"
      ? t("marketStats.insights.subjectPostings")
      : t(`marketStats.value.${insight.subject}`, { defaultValue: insight.subject });
  return t(key, {
    subject,
    pct: insight.delta_pct == null ? undefined : Math.abs(Math.round(insight.delta_pct)),
    interpolation: { escapeValue: false },
  });
}

type Translate = (key: string, options?: Record<string, unknown>) => string;
