import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useState } from "react";
import { Bookmark, Plus, Search, X } from "lucide-react";

import { explorePostings, fetchPostingSources } from "@/api/postings";
import { recordSearch, saveSearch } from "@/api/engagement";
import type { ExploreParams } from "@/types";
import { fetchSkillOntology } from "@/api/skills";
import { PostingCard } from "@/components/PostingCard";
import { PostingDetail } from "@/components/PostingDetail";
import { EmptyState, SearchableDropdown } from "@/components/ui";
import type { ExploreFacets, JobPostingItem, PostingSourceInfo } from "@/types";

const POSTED_WINDOWS = [
  { value: "", label: "any time" },
  { value: "24h", label: "last 24h" },
  { value: "7d", label: "last 7 days" },
  { value: "30d", label: "last 30 days" },
  { value: "90d", label: "last 90 days" },
];

const EMPTY_FACETS: ExploreFacets = {};

interface Filters {
  q: string;
  skills: { key: string; level: number | null }[];
  skillMode: "all" | "any";
  skillPriority: string;
  postedWithin: string;
  salaryMin: string;
  seniority: string[];
  remotePolicy: string;
  source: string[];
  extractedOnly: boolean;
  saved: boolean;
  sort: string;
  contract: string[];
  travel: string[];
  schedule: string[];
  org: string;
}

const INITIAL: Filters = {
  q: "",
  skills: [],
  skillMode: "all",
  skillPriority: "",
  postedWithin: "",
  salaryMin: "",
  seniority: [],
  remotePolicy: "",
  source: [],
  extractedOnly: false,
  saved: false,
  sort: "fit",
  contract: [],
  travel: [],
  schedule: [],
  org: "",
};

export function Explore() {
  const { t } = useTranslation();
  const [filters, setFilters] = useState<Filters>(INITIAL);
  const [items, setItems] = useState<JobPostingItem[]>([]);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState<ExploreFacets>(EMPTY_FACETS);
  const [cursor, setCursor] = useState<string | null>(null);
  const [sources, setSources] = useState<PostingSourceInfo[]>([]);
  const [skillOptions, setSkillOptions] = useState<{ value: string; label: string }[]>([]);
  const [skillKey, setSkillKey] = useState("");
  const [skillLevel, setSkillLevel] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [detailId, setDetailId] = useState<string | null>(null);
  const [savedNote, setSavedNote] = useState("");

  const paramsFrom = useCallback((current: Filters, nextCursor?: string | null): ExploreParams => {
    const params: ExploreParams = { sort: current.sort, limit: 20 };
    if (current.q) params.q = current.q;
    if (current.skills.length) {
      params.skills = current.skills
        .map((s) => (s.level ? `${s.key}:${s.level}` : s.key))
        .join(",");
      params.skill_mode = current.skillMode;
      if (current.skillPriority) params.skill_priority = current.skillPriority;
    }
    if (current.postedWithin) params.posted_within = current.postedWithin;
    if (current.salaryMin) params.salary_min = Number(current.salaryMin);
    if (current.seniority.length) params.seniority = current.seniority.join(",");
    if (current.remotePolicy) params.remote_policy = current.remotePolicy;
    if (current.source.length) params.source = current.source.join(",");
    if (current.contract.length) params.contract = current.contract.join(",");
    if (current.travel.length) params.travel = current.travel.join(",");
    if (current.schedule.length) params.schedule = current.schedule.join(",");
    if (current.org) params.org = current.org;
    if (current.extractedOnly) params.extracted_only = true;
    if (current.saved) params.saved = true;
    if (nextCursor) params.cursor = nextCursor;
    return params;
  }, []);

  const load = useCallback(
    (current: Filters, append: boolean) => {
      setError("");
      void explorePostings(paramsFrom(current, append ? cursor : null))
        .then((response) => {
          setItems((prev) => (append ? [...prev, ...response.items] : response.items));
          setTotal(response.total);
          setFacets(response.facets);
          setCursor(response.next_cursor);
        })
        .catch((err) => setError(String(err)));
    },
    [cursor, paramsFrom]
  );

  useEffect(() => {
    void fetchSkillOntology()
      .then((skills) =>
        setSkillOptions(
          skills
            .filter((s) => s.status === "active")
            .map((s) => ({ value: s.key, label: s.label }))
        )
      )
      .catch(() => setSkillOptions([]));
    void fetchPostingSources().then(setSources).catch(() => setSources([]));
  }, []);

  useEffect(() => {
    setCursor(null);
    load(filters, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  const patch = (update: Partial<Filters>) => setFilters((prev) => ({ ...prev, ...update }));

  const toggleIn = (list: string[], value: string) =>
    list.includes(value) ? list.filter((v) => v !== value) : [...list, value];

  const addSkillFilter = () => {
    if (!skillKey) return;
    patch({
      skills: filters.skills.some((s) => s.key === skillKey)
        ? filters.skills
        : [...filters.skills, { key: skillKey, level: skillLevel }],
    });
    setSkillKey("");
    setSkillLevel(null);
  };

  const saveThisSearch = () => {
    void recordSearch({
      scope: "postings",
      query: filters.q,
      filters: paramsFrom(filters) as unknown as Record<string, unknown>,
      result_count: total,
    })
      .then((record) => saveSearch(record.id))
      .then(() => {
        setSavedNote(t("explore.searchSaved"));
        setTimeout(() => setSavedNote(""), 4000);
      })
      .catch(() => setError(t("explore.saveFailed")));
  };

  const active =
    filters.q ||
    filters.skills.length ||
    filters.postedWithin ||
    filters.salaryMin ||
    filters.seniority.length ||
    filters.remotePolicy ||
    filters.source.length ||
    filters.extractedOnly ||
    filters.saved ||
    filters.contract.length ||
    filters.travel.length ||
    filters.schedule.length ||
    filters.org;

  const facetCount = (group: string, key: string): number | undefined =>
    facets[group]?.[key];

  return (
    <div className="space-y-6" data-testid="explore">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">
          Every open vacancy across your sources — filter, facet, deep-extract.
          {total ? ` ${total} matching.` : ""}
        </p>
        <button
          onClick={saveThisSearch}
          disabled={!active}
          className="text-sm flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-200 disabled:opacity-40"
          data-testid="save-search"
        >
          <Bookmark className="w-3.5 h-3.5" /> Save this search
        </button>
      </div>
      {savedNote && <p className="text-sm text-emerald-600" data-testid="saved-note">{savedNote}</p>}

      <div className="flex gap-6">
        <aside className="w-64 shrink-0 space-y-4" data-testid="explore-filters">
          <div className="bg-white border border-slate-200 rounded-xl p-3 space-y-3">
            <label className="flex items-center gap-2 text-sm">
              <Search className="w-4 h-4 text-slate-400" />
              <input
                value={filters.q}
                onChange={(e) => patch({ q: e.target.value })}
                placeholder={t("explore.searchPlaceholder")}
                className="w-full border border-slate-200 rounded-lg px-2 py-1.5"
                data-testid="explore-q"
              />
            </label>

            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase mb-1">Skills</p>
              <div className="flex gap-1.5">
                <div className="flex-1 min-w-0">
                  <SearchableDropdown
                    options={skillOptions}
                    value={skillKey}
                    onChange={(value) => setSkillKey(value)}
                    placeholder={t("explore.addSkill")}
                    clearable
                  />
                </div>
                <select
                  value={skillLevel ?? ""}
                  onChange={(e) => setSkillLevel(e.target.value ? Number(e.target.value) : null)}
                  className="text-xs border border-slate-200 rounded-lg px-1"
                  aria-label={t("explore.skillLevel")}
                  data-testid="level-select"
                >
                  <option value="">{t("explore.anyLevel")}</option>
                  {Array.from({ length: 10 }, (_, i) => (
                    <option key={i + 1} value={i + 1}>≥{i + 1}</option>
                  ))}
                </select>
                <button
                  onClick={addSkillFilter}
                  disabled={!skillKey}
                  className="text-xs px-2 py-1.5 rounded-lg bg-primary-600 text-white disabled:opacity-40"
                  aria-label={t("explore.addSkillFilter")}
                >
                  <Plus className="w-3 h-3" />
                </button>
              </div>
              {filters.skills.length > 0 && (
                <>
                  <select
                    value={filters.skillMode}
                    onChange={(e) => patch({ skillMode: e.target.value as "all" | "any" })}
                    className="text-xs border border-slate-200 rounded-lg px-1 mt-1.5 w-full"
                    aria-label={t("explore.skillMatchMode")}
                  >
                    <option value="all">{t("explore.allMustMatch")}</option>
                    <option value="any">{t("explore.anyMatches")}</option>
                  </select>
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {filters.skills.map((s) => (
                      <span
                        key={s.key}
                        className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded flex items-center gap-1"
                      >
                        {s.key}{s.level ? ` ≥${s.level}` : ""}
                        <button
                          onClick={() =>
                            patch({ skills: filters.skills.filter((f) => f.key !== s.key) })
                          }
                          aria-label={`Remove ${s.key}`}
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                </>
              )}
              {(facets.skills ? Object.keys(facets.skills) : []).length > 0 && !active && (
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {Object.entries(facets.skills)
                    .slice(0, 8)
                    .map(([key, count]) => (
                      <button
                        key={key}
                        onClick={() => patch({ skills: [...filters.skills, { key, level: null }] })}
                        className="text-[10px] bg-slate-50 text-slate-500 border border-slate-100 px-1.5 py-0.5 rounded hover:bg-primary-50"
                      >
                        {key} · {count}
                      </button>
                    ))}
                </div>
              )}
            </div>

            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase mb-1">{t("explore.posted")}</p>
              <select
                value={filters.postedWithin}
                onChange={(e) => patch({ postedWithin: e.target.value })}
                className="text-sm border border-slate-200 rounded-lg px-2 py-1.5 w-full"
                data-testid="posted-within"
              >
                {POSTED_WINDOWS.map((w) => (
                  <option key={w.value} value={w.value}>{w.label}</option>
                ))}
              </select>
              {!active && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {Object.entries(facets.posted ?? {}).map(([bucket, count]) => (
                    <button
                      key={bucket}
                      onClick={() => patch({ postedWithin: bucket === "older" ? "90d" : bucket })}
                      className="text-[10px] bg-slate-50 text-slate-500 border border-slate-100 px-1.5 py-0.5 rounded"
                    >
                      {bucket} · {count}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase mb-1">{t("explore.salaryFrom")}</p>
              <input
                value={filters.salaryMin}
                onChange={(e) => patch({ salaryMin: e.target.value.replace(/[^0-9]/g, "") })}
                placeholder={t("explore.salaryExample")}
                className="w-full border border-slate-200 rounded-lg px-2 py-1.5 text-sm"
                data-testid="salary-min"
              />
            </div>

            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase mb-1">{t("explore.seniority")}</p>
              <div className="flex flex-wrap gap-1">
                {Object.entries(facets.seniority ?? {}).map(([value, count]) => (
                  <button
                    key={value}
                    onClick={() => patch({ seniority: toggleIn(filters.seniority, value) })}
                    className={`text-xs px-2 py-0.5 rounded border ${
                      filters.seniority.includes(value)
                        ? "bg-primary-600 text-white border-primary-600"
                        : "border-slate-200 text-slate-600"
                    }`}
                  >
                    {value} · {count}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase mb-1">Work mode</p>
              <div className="flex flex-wrap gap-1">
                {Object.entries(facets.remote_policy ?? {}).map(([value, count]) => (
                  <button
                    key={value}
                    onClick={() => patch({ remotePolicy: filters.remotePolicy === value ? "" : value })}
                    className={`text-xs px-2 py-0.5 rounded border ${
                      filters.remotePolicy === value
                        ? "bg-primary-600 text-white border-primary-600"
                        : "border-slate-200 text-slate-600"
                    }`}
                  >
                    {value} · {count}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase mb-1">Contract</p>
              <div className="flex flex-wrap gap-1">
                {["permanent", "temporary", "contract", "freelance", "b2b", "internship", "apprenticeship"].map(
                  (value) => (
                    <button
                      key={value}
                      onClick={() => patch({ contract: toggleIn(filters.contract, value) })}
                      className={`text-xs px-2 py-0.5 rounded border ${
                        filters.contract.includes(value)
                          ? "bg-primary-600 text-white border-primary-600"
                          : "border-slate-200 text-slate-600"
                      }`}
                      data-testid={`contract-${value}`}
                    >
                      {value.replace(/_/g, " ")}
                    </button>
                  ),
                )}
              </div>
            </div>

            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase mb-1">Travel</p>
              <div className="flex flex-wrap gap-1">
                {["none", "occasional", "frequent"].map((value) => (
                  <button
                    key={value}
                    onClick={() => patch({ travel: toggleIn(filters.travel, value) })}
                    className={`text-xs px-2 py-0.5 rounded border ${
                      filters.travel.includes(value)
                        ? "bg-primary-600 text-white border-primary-600"
                        : "border-slate-200 text-slate-600"
                    }`}
                    data-testid={`travel-${value}`}
                  >
                    {value}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase mb-1">Schedule</p>
              <div className="flex flex-wrap gap-1">
                {["shift_work", "on_call", "nights", "weekends", "flexible"].map((value) => (
                  <button
                    key={value}
                    onClick={() => patch({ schedule: toggleIn(filters.schedule, value) })}
                    className={`text-xs px-2 py-0.5 rounded border ${
                      filters.schedule.includes(value)
                        ? "bg-primary-600 text-white border-primary-600"
                        : "border-slate-200 text-slate-600"
                    }`}
                    data-testid={`schedule-${value}`}
                  >
                    {value.replace(/_/g, " ")}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase mb-1">Organization</p>
              <input
                value={filters.org}
                onChange={(e) => patch({ org: e.target.value })}
                placeholder={t("explore.orgExample")}
                className="w-full border border-slate-200 rounded-lg px-2 py-1.5 text-sm"
                data-testid="org-filter"
              />
            </div>

            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase mb-1">Sources</p>
              <div className="space-y-1">
                {sources.map((s) => (
                  <label key={s.key} className="flex items-center justify-between text-xs text-slate-600">
                    <span className="flex items-center gap-1">
                      <input
                        type="checkbox"
                        checked={filters.source.includes(s.key)}
                        onChange={() => patch({ source: toggleIn(filters.source, s.key) })}
                      />
                      {s.key}
                    </span>
                    <span className="text-slate-400">
                      {facetCount("source", s.key) ?? s.open_postings}
                    </span>
                  </label>
                ))}
                {sources.length === 0 && (
                  <p className="text-xs text-slate-400">No sources connected yet.</p>
                )}
              </div>
            </div>

            <label className="flex items-center justify-between text-xs text-slate-600">
              <span>{t("explore.deepExtractedOnly")}</span>
              <input
                type="checkbox"
                checked={filters.extractedOnly}
                onChange={(e) => patch({ extractedOnly: e.target.checked })}
                data-testid="extracted-only"
              />
            </label>
            <label className="flex items-center justify-between text-xs text-slate-600">
              <span>{t("explore.savedOnly")}</span>
              <input
                type="checkbox"
                checked={filters.saved}
                onChange={(e) => patch({ saved: e.target.checked })}
                data-testid="saved-only"
              />
            </label>

            {active && (
              <button
                onClick={() => setFilters(INITIAL)}
                className="text-xs text-slate-400 hover:text-slate-600"
                data-testid="clear-filters"
              >
                Clear all filters
              </button>
            )}
          </div>
        </aside>

        <div className="flex-1 space-y-3">
          {error && <p className="text-sm text-rose-600">{error}</p>}
          {items.length === 0 && !error && (
            <EmptyState
              title={t("explore.nothingMatches")}
              description={t("explore.nothingMatchesBody")}
            />
          )}
          {items.map((posting) => (
            <PostingCard
              key={posting.id}
              posting={posting}
              onOpenDetail={() => setDetailId(posting.id)}
              onChanged={() => load(filters, false)}
            />
          ))}
          {cursor && (
            <button
              onClick={() => load(filters, true)}
              className="text-sm text-primary-700 hover:underline"
              data-testid="load-more"
            >
              {t("explore.loadMore")}
            </button>
          )}
        </div>
      </div>
      {detailId && <PostingDetail postingId={detailId} onClose={() => setDetailId(null)} />}
    </div>
  );
}
