import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { fetchRankings, rateJob } from "@/api/matching";
import { fetchProfile } from "@/api/profile";
import { DemandBadge } from "@/components/DemandBadge";
import { ScoreRing } from "@/components/ScoreRing";
import { WeightsEditor } from "@/components/WeightsEditor";
import { RecentSearches } from "@/components/RecentSearches";
import { EmptyState, SearchableDropdown } from "@/components/ui";
import { useSearchHistory } from "@/hooks/useSearchHistory";
import type { FitBreakdown, MatchStatus, RankedJob, ScoringWeights, SearchRecord } from "@/types";

const FAMILY_OPTIONS = [
  "technology", "healthcare", "education", "engineering", "business",
  "creative", "public-safety", "science", "agriculture", "hospitality",
].map((f) => ({ value: f, label: f.replace(/-/g, " ") }));

const DEMAND_OPTIONS = ["hot", "growing", "stable", "declining"].map((d) => ({ value: d, label: d }));
const STATUS_OPTIONS = ["interested", "considering", "dismissed"].map((s) => ({ value: s, label: s }));
const SORT_OPTIONS = [
  { value: "fit", label: "Best fit" },
  { value: "ai_score", label: "AI score" },
  { value: "user_score", label: "My score" },
  { value: "demand", label: "Demand" },
];

const DIMENSION_LABELS: Record<string, string> = {
  skills: "Skills",
  interests: "Interests & style",
  education: "Education",
  experience: "Experience",
  location: "Location",
};

export function Rankings() {
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
      <h1 className="text-2xl font-bold text-slate-900">
        {stretch ? "Stretch goals" : "Your job rankings"}
      </h1>
      <div className="grid lg:grid-cols-[260px_1fr] gap-6">
        <aside className="bg-white border border-slate-200 rounded-xl p-4 space-y-4" data-testid="filter-bar">
          <label className="block">
            <span className="text-xs font-medium text-slate-400 uppercase">Search</span>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="nurse, data…"
              className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
            />
          </label>
          <RecentSearches scope="rankings" onApply={applySearch} refreshKey={historyKey} />
          <div>
            <span className="text-xs font-medium text-slate-400 uppercase">Family</span>
            <div className="mt-1">
              <SearchableDropdown
                options={[{ value: "", label: "All families" }, ...FAMILY_OPTIONS]}
                value={family}
                onChange={setFamily}
                placeholder="All families"
              />
            </div>
          </div>
          <label className="block">
            <span className="text-xs font-medium text-slate-400 uppercase">Interest (taxonomy key)</span>
            <input
              value={interests}
              onChange={(e) => setInterests(e.target.value)}
              placeholder="technology-software"
              className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
            />
          </label>
          <div>
            <span className="text-xs font-medium text-slate-400 uppercase">Demand</span>
            <div className="mt-1">
              <SearchableDropdown
                options={[{ value: "", label: "Any demand" }, ...DEMAND_OPTIONS]}
                value={demand}
                onChange={setDemand}
                placeholder="Any demand"
              />
            </div>
          </div>
          <div>
            <span className="text-xs font-medium text-slate-400 uppercase">My status</span>
            <div className="mt-1">
              <SearchableDropdown
                options={[{ value: "", label: "Any status" }, ...STATUS_OPTIONS]}
                value={status}
                onChange={setStatus}
                placeholder="Any status"
              />
            </div>
          </div>
          <label className="block">
            <span className="text-xs font-medium text-slate-400 uppercase">Min score: {minScore ?? 0}</span>
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
            Stretch goals only
          </label>
          <div className="pt-2 border-t border-slate-100">
            <h3 className="text-xs font-medium text-slate-400 uppercase mb-2">Score distribution</h3>
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
              {total} jobs{stretch ? " · gated (excluded from your feed)" : ""}
            </p>
            <div className="flex gap-2 items-center">
              <button
                onClick={() => setShowWeights((v) => !v)}
                className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 hover:border-primary-400"
                data-testid="adjust-weights"
              >
                {showWeights ? "Hide weights" : "Adjust weights"}
              </button>
              <div className="w-40">
                <SearchableDropdown options={SORT_OPTIONS} value={sort} onChange={setSort} />
              </div>
            </div>
          </div>
          {showWeights && weights && (
            <div className="bg-primary-50 border border-primary-100 rounded-xl p-4">
              <p className="text-xs text-slate-500 mb-2">
                How much each dimension matters to you (1–5). Saving refits every job instantly — no AI cost.
              </p>
              <WeightsEditor
                initial={weights}
                onSaved={() => load()}
              />
            </div>
          )}
          {items.length === 0 ? (
            <EmptyState
              title={stretch ? "No gated jobs" : "No jobs match these filters"}
              description={
                stretch
                  ? "Jobs that hit a hard constraint (like an education-years cap) appear here with explanations."
                  : "Loosen the filters, or score some candidates to unlock AI-ranked results."
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
                      Strong in {DIMENSION_LABELS[r.specialist_dimension] ?? r.specialist_dimension}
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
                  <span>fit {Number(r.fit_score).toFixed(1)}</span>
                  <span>AI {r.ai_score != null ? Number(r.ai_score).toFixed(1) : "–"}</span>
                  <span>you {r.user_score ?? "–"}</span>
                  <button
                    onClick={() => setExpanded(expanded === r.job.id ? null : r.job.id)}
                    className="text-primary-700 hover:underline"
                    data-testid={`breakdown-toggle-${r.job.code}`}
                  >
                    {expanded === r.job.id ? "hide breakdown" : "why?"}
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
                    {s === "interested" ? "♥ interested" : "✕ dismiss"}
                  </button>
                ))}
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
  const dims = Object.entries(breakdown.dimensions);
  return (
    <div className="mt-2 space-y-1.5" data-testid="fit-breakdown">
      {dims.map(([dim, entry]) => (
        <div key={dim} className="flex items-center gap-2">
          <span className="text-xs text-slate-400 w-28 shrink-0">
            {DIMENSION_LABELS[dim] ?? dim}
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
          {dims.map(([dim, entry]) => `${DIMENSION_LABELS[dim] ?? dim}: ${entry.detail}`).join(" · ")}
        </p>
      )}
    </div>
  );
}
