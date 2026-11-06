import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useTranslation } from "react-i18next";
import type { MarketTrendPoint } from "@/api/growth";

/**
 * Demand-history strip: p25–p75 salary band movement across
 * the persisted daily snapshots. Renders nothing below 2 points — a
 * single capture is history-in-the-making, not a trend.
 */
export function MarketTrendStrip({ history }: { history: MarketTrendPoint[] }) {
  const { t } = useTranslation();
  if (history.length < 2) return null;
  const points = history.map((h) => ({
    date: h.capture_date.slice(5),
    p25: h.salary_band?.p25 ?? null,
    p75: h.salary_band?.p75 ?? null,
    sample: h.sample_size,
  }));
  return (
    <div className="mt-2" data-testid="market-trend">
      <p className="text-xs uppercase text-slate-400">{t("shared.demandHistory")}</p>
      <ResponsiveContainer width="100%" height={90}>
        <LineChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
          <XAxis dataKey="date" tick={{ fontSize: 9 }} />
          <YAxis tick={{ fontSize: 9 }} width={44} />
          <Tooltip
            formatter={(value: number | string, name: string) => [
              typeof value === "number" ? value.toLocaleString() : String(value),
              name === "p25" ? "p25" : name === "p75" ? "p75" : name,
            ]}
          />
          <Line type="monotone" dataKey="p25" stroke="#3b82f6" dot={false} strokeWidth={2} />
          <Line type="monotone" dataKey="p75" stroke="#10b981" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
      <p className="text-xs text-slate-400">
        {t("shared.snapshotCount", {
          count: history.length,
        })}
      </p>
    </div>
  );
}
