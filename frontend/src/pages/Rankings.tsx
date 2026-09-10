import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { fetchRankings, rateJob } from "@/api/matching";
import { fetchProfile } from "@/api/profile";
import { DemandBadge } from "@/components/DemandBadge";
import { ScoreRing } from "@/components/ScoreRing";
import { WeightsEditor } from "@/components/WeightsEditor";
import { RecentSearches } from "@/components/RecentSearches";
import { FitStaleBadge } from "@/components/FitStaleBadge";
import { EmptyState, SearchableDropdown } from "@/components/ui";
import { useSearchHistory } from "@/hooks/useSearchHistory";
import { dimensionKey } from "@/lib/fitDimensions";
import { useCompareStore } from "@/stores/compareStore";
import type { FitBreakdown, MatchStatus, RankedJob, ScoringWeights, SearchRecord } from "@/types";

const FAMILY_KEYS = [
  "technology", "healthcare", "education", "engineering", "business",
  "creative", "public-safety", "science", "agriculture", "hospitality",
];

const DEMAND_OPTIONS = ["hot", "growing", "stable", "declining"].map((d) => ({ value: d, label: d }));
const STATUS_OPTIONS = ["interested", "considering", "dismissed"].map((s) => ({ value: s, label: s }));
const SORT_KEYS: Record<string, string> = {
  fit: "rankings.sortBestFit",
  ai_score: "rankings.sortAiScore",
  user_score: "rankings.sortMyScore",
  demand: "rankings.sortDemand",
};

export function Rankings() {
  const { t } = useTranslation();
  const [items, setItems] = useState<RankedJob[]>([]);
  const [total, setTotal] = useState(0);
  const [family, setFamily] = useState("");
  const [interests, setInterests] = useState("");
  const [demand, setDemand] = useState("");
  const [sort, setSort] = useState("fit");
  const [q, setQ] = useState("");
  const [minScore, setMinScore] = useState<number | null>(null);
  const [status, setStatus] = useState("");
  const [stretch, setStretch] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [weights, setWeights] = useState<ScoringWeights | null>(null);
  const [showWeights, setShowWeights] = useState(false);
  const [historyKey, setHistoryKey] = useState(0);
  const compareItems = useCompareStore((s) => s.items);
  const toggleCompare = useCompareStore((s) => s.toggle);
  const recordSearch = useSearchHistory("rankings");
  const recordRef = useRef(recordSearch);
  recordRef.current = recordSearch;

  const load = () => {
    void fetchRankings({
      family_key: family || undefined,
      interests: interests || undefined,
      demand: demand || undefined,
      sort,
      q: q || undefined,
      ai_score_min: minScore ?? undefined,
      status: status || undefined,
      stretch,
      page_size: 50,
    }).then((r) => {
      setItems(r.items);
      setTotal(r.total);
      recordRef.current(
        q,
        {
          family_key: family || null,
          interests: interests || null,
          demand: demand || null,
          sort,
          ai_score_min: minScore ?? null,
          status: status || null,
          stretch,
        },
        r.total
      );
    });
  };

  const applySearch = (record: SearchRecord) => {
    const filters = record.filters;
    setQ(record.query);
    setFamily((filters.family_key as string) || "");
    setInterests((filters.interests as string) || "");
    setDemand((filters.demand as string) || "");
    setSort((filters.sort as string) || "fit");
    setMinScore((filters.ai_score_min as number) ?? null);
    setStatus((filters.status as string) || "");
    setStretch(Boolean(filters.stretch));
    setHistoryKey((k) => k + 1);
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [family, interests, demand, sort, q, minScore, status, stretch]);

  useEffect(() => {
    if (showWeights && !weights) {
      void fetchProfile().then((p) => setWeights(p.preferences.scoring_weights));
    }
  }, [showWeights, weights]);

  const distribution = useMemo(() => {
    const buckets = [
      { range: "0–2", n: 0 },
      { range: "2–4", n: 0 },
      { range: "4–6", n: 0 },
      { range: "6–8", n: 0 },
      { range: "8–10", n: 0 },
    ];
    for (const item of items) {
      const s = item.score;
      const idx = Math.min(4, Math.floor(s / 2));
      buckets[idx].n += 1;
    }
    return buckets;
  }, [items]);

  return (
    <div className="space-y-6" data-testid="rankings">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold text-slate-900">
          {t(stretch ? "rankings.titleStretch" : "rankings.title")}
        </h1>
        <FitStaleBadge />
      </div>
      <div className="grid lg:grid-cols-[260px_1fr] gap-6">
        <aside className="bg-white border border-slate-200 rounded-xl p-4 space-y-4" data-testid="filter-bar">
          <label className="block">
            <span className="text-xs font-medium text-slate-400 uppercase">{t("rankings.search")}</span>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t("rankings.searchPlaceholder")}
              className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
            />
          </label>
          <RecentSearches scope="rankings" onApply={applySearch} refreshKey={historyKey} />
          <div>
            <span className="text-xs font-medium text-slate-400 uppercase">{t("rankings.family")}</span>
            <div className="mt-1">
              <SearchableDropdown
                options={[{ value: "", label: t("rankings.allFamilies") }, ...FAMILY_KEYS.map((f) => ({ value: f, label: t(`families.${f}`, { defaultValue: f.replace(/-/g, " ") }) }))]}
                value={family}
                onChange={setFamily}
                placeholder={t("rankings.allFamilies")}
              />
            </div>
          </div>
          <label className="block">
            <span className="text-xs font-medium text-slate-400 uppercase">{t("rankings.interest")}</span>
            <input
              value={interests}
              onChange={(e) => setInterests(e.target.value)}
              placeholder={t("rankings.interestPlaceholder")}
              className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
            />
          </label>
          <div>
            <span className="text-xs font-medium text-slate-400 uppercase">{t("rankings.demand")}</span>
            <div className="mt-1">
              <SearchableDropdown
                options={[{ value: "", label: t("rankings.anyDemand") }, ...DEMAND_OPTIONS]}
                value={demand}
                onChange={setDemand}
                placeholder={t("rankings.anyDemand")}
              />
            </div>
          </div>
          <div>
            <span className="text-xs font-medium text-slate-400 uppercase">{t("rankings.myStatus")}</span>
            <div className="mt-1">
              <SearchableDropdown
                options={[{ value: "", label: t("rankings.anyStatus") }, ...STATUS_OPTIONS]}
                value={status}
                onChange={setStatus}
                placeholder={t("rankings.anyStatus")}
              />
            </div>
          </div>
          <label className="block">
            <span className="text-xs font-medium text-slate-400 uppercase">{t("rankings.minScore", { score: minScore ?? 0 })}</span>
            <input
              type="range"
              min={0}
              max={10}
              step={0.5}
              value={minScore ?? 0}
              onChange={(e) => setMinScore(Number(e.target.value))}
              className="mt-1 w-full accent-primary-600"
            />
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={stretch}
              onChange={(e) => setStretch(e.target.checked)}
              className="accent-primary-600"
            />
            {t("rankings.stretchOnly")}
          </label>
          <div className="pt-2 border-t border-slate-100">
            <h3 className="text-xs font-medium text-slate-400 uppercase mb-2">{t("rankings.scoreDistribution")}</h3>
            <ResponsiveContainer width="100%" height={120}>
              <BarChart data={distribution}>
                <XAxis dataKey="range" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="n" fill="#3b82f6" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </aside>

        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm text-slate-500">
              {t("rankings.totalJobs", { total })}{stretch ? t("rankings.gatedSuffix") : ""}
            </p>
            <div className="flex gap-2 items-center">
              <button
                onClick={() => setShowWeights((v) => !v)}
                className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 hover:border-primary-400"
                data-testid="adjust-weights"
              >
                {showWeights ? t("rankings.hideWeights") : t("rankings.adjustWeights")}
              </button>
              <div className="w-40">
                <SearchableDropdown options={Object.entries(SORT_KEYS).map(([value, key]) => ({ value, label: t(key) }))} value={sort} onChange={setSort} />
              </div>
            </div>
          </div>
          {showWeights && weights && (
            <div className="bg-primary-50 border border-primary-100 rounded-xl p-4">
              <p className="text-xs text-slate-500 mb-2">
                {t("rankings.weightsHint")}
              </p>
              <WeightsEditor
                initial={weights}
                onSaved={() => load()}
              />
            </div>
          )}
          {items.length === 0 ? (
            <EmptyState
              title={t(stretch ? "rankings.emptyTitleGated" : "rankings.emptyTitle")}
              description={
                t(stretch ? "rankings.emptyBodyGated" : "rankings.emptyBody")
              }
            />
          ) : (
            items.map((r) => (
            <div key={r.job.id} className="bg-white border border-slate-200 rounded-xl p-4 flex items-center gap-4">
              <ScoreRing score={r.score} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <Link to={`/jobs/${r.job.code}`} className="font-medium text-slate-900 hover:text-primary-700 truncate">
                    {r.job.title}
                  </Link>
                  <DemandBadge outlook={r.job.attributes?.demand?.outlook} />
                  {r.specialist_dimension && (
                    <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full">
                      {t("rankings.strongIn", { dimension: t(dimensionKey(r.specialist_dimension)) })}
                    </span>
                  )}
                  {r.gated && r.gate_reasons.length > 0 && (
                    <span className="text-xs bg-rose-100 text-rose-700 px-2 py-0.5 rounded-full">
                      {r.gate_reasons.join(", ")}
                    </span>
                  )}
                </div>
                <p className="text-sm text-slate-500 truncate">{r.job.short_description}</p>
                <div className="flex gap-3 mt-1 text-xs text-slate-400">
                  <span>{t("rankings.fit")} {Number(r.fit_score).toFixed(1)}</span>
                  <span>{t("rankings.aiScore")} {r.ai_score != null ? Number(r.ai_score).toFixed(1) : "–"}</span>
                  <span>{t("rankings.yourScore")} {r.user_score ?? "–"}</span>
                  <button
                    onClick={() => setExpanded(expanded === r.job.id ? null : r.job.id)}
                    className="text-primary-700 hover:underline"
                    data-testid={`breakdown-toggle-${r.job.code}`}
                  >
                    {expanded === r.job.id ? t("rankings.hideBreakdown") : t("rankings.why")}
                  </button>
                </div>
                {expanded === r.job.id && r.breakdown && (
                  <FitBars breakdown={r.breakdown} />
                )}
              </div>
              <div className="flex flex-col gap-1">
                {(["interested", "dismissed"] as MatchStatus[]).map((s) => (
                  <button
                    key={s}
                    onClick={async () => {
                      await rateJob({ job_id: r.job.id, status: s });
                      setItems((prev) =>
                        prev.map((x) => (x.job.id === r.job.id ? { ...x, status: s } : x))
                      );
                    }}
                    className={`text-xs px-2.5 py-1 rounded-full border ${
                      r.status === s ? "bg-primary-600 text-white border-primary-600" : "border-slate-200"
                    }`}
                  >
                    {s === "interested" ? t("rankings.interested") : t("rankings.dismiss")}
                  </button>
                ))}
                <button
                  onClick={() => toggleCompare({ id: r.job.id, title: r.job.title })}
                  className={`text-xs px-2.5 py-1 rounded-full border ${
                    compareItems.some((i) => i.id === r.job.id)
                      ? "bg-emerald-600 text-white border-emerald-600"
                      : "border-slate-200 text-slate-600"
                  }`}
                  data-testid={`compare-add-${r.job.code}`}
                >
                  {compareItems.some((i) => i.id === r.job.id) ? t("rankings.comparing") : t("rankings.compare")}
                </button>
              </div>
            </div>
            ))
          )}
        </section>
      </div>
    </div>
  );
}

export function FitBars({ breakdown }: { breakdown: FitBreakdown }) {
  const { t } = useTranslation();
  const dims = Object.entries(breakdown.dimensions);
  return (
    <div className="mt-2 space-y-1.5" data-testid="fit-breakdown">
      {dims.map(([dim, entry]) => (
        <div key={dim} className="flex items-center gap-2">
          <span className="text-xs text-slate-400 w-28 shrink-0">
            {t(dimensionKey(dim), { defaultValue: dim })}
            {entry.weight !== 3 && (
              <span className="text-slate-300"> ×{entry.weight}</span>
            )}
          </span>
          <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
            <div
              className={`h-1.5 rounded-full ${entry.score >= 7 ? "bg-emerald-500" : entry.score >= 4 ? "bg-amber-500" : "bg-rose-400"}`}
              style={{ width: `${(entry.score / 10) * 100}%` }}
            />
          </div>
          <span className="text-xs text-slate-400 w-8 text-right">{Number(entry.score).toFixed(1)}</span>
        </div>
      ))}
      {dims.length > 0 && (
        <p className="text-xs text-slate-400 pt-0.5">
          {dims.map(([dim, entry]) => `${t(dimensionKey(dim), { defaultValue: dim })}: ${entry.detail}`).join(" · ")}
        </p>
      )}
    </div>
  );
}
