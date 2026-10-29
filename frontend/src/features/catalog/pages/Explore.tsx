import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bookmark, Radar, Search, X } from "lucide-react";

import { explorePostings, fetchPostingSources } from "@/api/postings";
import { recordSearch, saveSearch } from "@/api/engagement";
import { fetchRadar, previewRadar } from "@/api/radar";
import { apiDetail } from "@/api/client";
import type { ExploreParams } from "@/types";
import { fetchSkillOntology } from "@/api/skills";
import { PostingCard } from "@/features/postings/components/PostingCard";
import { EmptyState, Spinner } from "@/components/ui";
import type { ExploreFacets, PostingSourceInfo } from "@/types/wire";
import type { PostingOut } from "@/types/wire";
import { SkillPicker } from "@/features/postings/components/postings/SkillPicker";
import { OrgPicker } from "@/features/postings/components/postings/OrgPicker";
import {
  Section,
  TriStateChips,
  triStateToggle,
} from "@/features/postings/components/postings/filterBits";

const POSTED_WINDOWS = [
  { value: "24h", labelKey: "explore.posted.h24" },
  { value: "7d", labelKey: "explore.posted.d7" },
  { value: "30d", labelKey: "explore.posted.d30" },
  { value: "90d", labelKey: "explore.posted.d90" },
];

const CONTRACT_VALUES = [
  "permanent",
  "temporary",
  "contract",
  "freelance",
  "b2b",
  "internship",
  "apprenticeship",
];

const TRAVEL_VALUES = ["none", "occasional", "frequent"];
const SCHEDULE_VALUES = ["shift_work", "on_call", "nights", "weekends", "flexible"];

const EMPTY_FACETS: ExploreFacets = {};

interface Filters {
  q: string;
  skills: { key: string; level: number | null }[];
  skillsExclude: string[];
  skillMode: "all" | "any";
  postedWithin: string;
  salaryMin: string;
  seniority: string[];
  seniorityExclude: string[];
  remotePolicy: string[];
  remotePolicyExclude: string[];
  source: string[];
  sourceExclude: string[];
  extractedOnly: boolean;
  saved: boolean;
  sort: string;
  contract: string[];
  contractExclude: string[];
  travel: string[];
  travelExclude: string[];
  schedule: string[];
  scheduleExclude: string[];
  orgs: string[];
  orgsExclude: string[];
}

const INITIAL: Filters = {
  q: "",
  skills: [],
  skillsExclude: [],
  skillMode: "all",
  postedWithin: "",
  salaryMin: "",
  seniority: [],
  seniorityExclude: [],
  remotePolicy: [],
  remotePolicyExclude: [],
  source: [],
  sourceExclude: [],
  extractedOnly: false,
  saved: false,
  sort: "fit",
  contract: [],
  contractExclude: [],
  travel: [],
  travelExclude: [],
  schedule: [],
  scheduleExclude: [],
  orgs: [],
  orgsExclude: [],
};

function countActive(f: Filters): number {
  let n = 0;
  if (f.q) n++;
  n += f.skills.length + f.skillsExclude.length;
  if (f.skillMode !== "all" && f.skills.length) n++;
  if (f.postedWithin) n++;
  if (f.salaryMin) n++;
  n += f.seniority.length + f.seniorityExclude.length;
  n += f.remotePolicy.length + f.remotePolicyExclude.length;
  n += f.source.length + f.sourceExclude.length;
  n += f.contract.length + f.contractExclude.length;
  n += f.travel.length + f.travelExclude.length;
  n += f.schedule.length + f.scheduleExclude.length;
  n += f.orgs.length + f.orgsExclude.length;
  if (f.extractedOnly) n++;
  if (f.saved) n++;
  return n;
}

export function Explore() {
  const { t } = useTranslation();
  const [filters, setFilters] = useState<Filters>(INITIAL);
  const [items, setItems] = useState<PostingOut[]>([]);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState<ExploreFacets>(EMPTY_FACETS);
  const [cursor, setCursor] = useState<string | null>(null);
  const [sources, setSources] = useState<PostingSourceInfo[]>([]);
  const [skillOptions, setSkillOptions] = useState<{ value: string; label: string }[]>([]);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const [savedNote, setSavedNote] = useState("");
  const [radarActive, setRadarActive] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const loadingRef = useRef(false);
  const filtersRef = useRef(filters);

  const paramsFrom = useCallback((current: Filters, nextCursor?: string | null): ExploreParams => {
    const params: ExploreParams = { sort: current.sort, limit: 20 };
    if (current.q) params.q = current.q;
    if (current.skills.length) {
      params.skills = current.skills
        .map((s) => (s.level ? `${s.key}:${s.level}` : s.key))
        .join(",");
      params.skill_mode = current.skillMode;
    }
    if (current.skillsExclude.length) params.skill_exclude = current.skillsExclude.join(",");
    if (current.postedWithin) params.posted_within = current.postedWithin;
    if (current.salaryMin) params.salary_min = Number(current.salaryMin);
    if (current.seniority.length) params.seniority = current.seniority.join(",");
    if (current.seniorityExclude.length)
      params.seniority_exclude = current.seniorityExclude.join(",");
    if (current.remotePolicy.length) params.remote_policy = current.remotePolicy.join(",");
    if (current.remotePolicyExclude.length)
      params.remote_policy_exclude = current.remotePolicyExclude.join(",");
    if (current.source.length) params.source = current.source.join(",");
    if (current.sourceExclude.length) params.source_exclude = current.sourceExclude.join(",");
    if (current.contract.length) params.contract = current.contract.join(",");
    if (current.contractExclude.length)
      params.contract_exclude = current.contractExclude.join(",");
    if (current.travel.length) params.travel = current.travel.join(",");
    if (current.travelExclude.length) params.travel_exclude = current.travelExclude.join(",");
    if (current.schedule.length) params.schedule = current.schedule.join(",");
    if (current.scheduleExclude.length)
      params.schedule_exclude = current.scheduleExclude.join(",");
    if (current.orgs.length) params.org = current.orgs;
    if (current.orgsExclude.length) params.org_exclude = current.orgsExclude;
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
          setFacets(response.facets ?? {});
          setCursor(response.next_cursor ?? null);
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
    setRadarActive(false);
    setCursor(null);
    load(filters, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  const patch = (update: Partial<Filters>) => setFilters((prev) => ({ ...prev, ...update }));

  useEffect(() => {
    filtersRef.current = filters;
  }, [filters]);

  const loadMore = useCallback(() => {
    if (!cursor || loadingRef.current || radarActive) return;
    const requestFilters = filters;
    loadingRef.current = true;
    setLoadingMore(true);
    setError("");
    void explorePostings(paramsFrom(requestFilters, cursor))
      .then((response) => {
        // a filter change that landed mid-flight re-owns the list —
        // the stale page is dropped, never appended to it
        if (requestFilters !== filtersRef.current) return;
        setItems((prev) => [...prev, ...response.items]);
        setTotal(response.total);
        setFacets(response.facets ?? {});
        setCursor(response.next_cursor ?? null);
      })
      .catch((err) => setError(String(err)))
      .finally(() => {
        loadingRef.current = false;
        setLoadingMore(false);
      });
  }, [cursor, filters, paramsFrom, radarActive]);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || !cursor || radarActive) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) loadMore();
      },
      // start fetching just before the user reaches the end
      { rootMargin: "480px 0px" }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [cursor, radarActive, loadMore]);

  const addSkillFilter = (key: string) => {
    if (!key || filters.skills.some((s) => s.key === key)) return;
    patch({ skills: [...filters.skills, { key, level: null }] });
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

  const applyRadar = async () => {
    setError("");
    try {
      const radar = await fetchRadar();
      const configured =
        (radar.keywords ?? []).length > 0 ||
        (radar.locations ?? []).length > 0 ||
        radar.onsite_policy ||
        radar.salary_min_annual != null ||
        (radar.seniority ?? []).length > 0;
      if (!configured) {
        setSavedNote(t("explore.radarNotConfigured"));
        return;
      }
      const response = await previewRadar({
        keywords: radar.keywords ?? [],
        locations: radar.locations ?? [],
        seniority: radar.seniority ?? [],
        onsite_policy: radar.onsite_policy ?? null,
        salary_min_annual: radar.salary_min_annual ?? null,
        salary_currency: radar.salary_currency ?? null,
        source_keys: radar.source_keys ?? [],
        cadence: radar.cadence ?? "off",
        enabled: true,
      });
      setItems(response.items);
      setTotal(response.total);
      setFacets(response.facets ?? {});
      setCursor(null);
      setRadarActive(true);
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const clearRadar = () => {
    setRadarActive(false);
    setFilters(INITIAL);
    setCursor(null);
  };

  const activeCount = countActive(filters);
  const active = activeCount > 0;

  const facetCount = (group: string, key: string): number | undefined =>
    (facets ?? {})[group]?.[key];

  return (
    <div className="space-y-6" data-testid="explore">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="min-w-0 flex-1 text-sm text-slate-500">
          {radarActive ? t("explore.radarActive") : t("explore.intro")}
          {total ? ` ${total} matching.` : ""}
        </p>
        <div className="flex items-center gap-2">
          {radarActive ? (
            <button
              onClick={clearRadar}
              className="text-sm flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-200"
              data-testid="radar-clear"
            >
              {t("explore.radarClear")}
            </button>
          ) : (
            <button
              onClick={() => void applyRadar()}
              className="text-sm flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-200"
              data-testid="radar-apply"
            >
              <Radar className="w-3.5 h-3.5" /> {t("explore.radarApply")}
            </button>
          )}
          <button
            onClick={saveThisSearch}
            disabled={!active}
            className="text-sm flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-200 disabled:opacity-40"
            data-testid="save-search"
          >
            <Bookmark className="w-3.5 h-3.5" /> {t("explore.saveSearch")}
          </button>
        </div>
      </div>
      {savedNote && <p className="text-sm text-emerald-600" data-testid="saved-note">{savedNote}</p>}

      <div className="flex gap-6">
        <aside
          className="w-64 shrink-0 self-start sticky top-16 max-h-[calc(100vh-5rem)]"
          data-testid="explore-filters"
        >
          <div className="bg-white border border-slate-200 rounded-xl p-3 space-y-3 max-h-full overflow-y-auto">
            <div className="flex items-center justify-between gap-2">
              <div className="text-sm font-semibold text-slate-700">
                {t("filters.title")}
                {activeCount > 0 ? (
                  <span className="ml-2 text-xs text-primary-600" data-testid="explore-filter-count">
                    {t("filters.activeCount", { count: activeCount })}
                  </span>
                ) : null}
              </div>
              {active ? (
                <button
                  onClick={() => setFilters(INITIAL)}
                  className="text-xs text-slate-400 hover:text-slate-600"
                  data-testid="clear-filters"
                >
                  {t("explore.clearAllFilters")}
                </button>
              ) : null}
            </div>

            <label className="flex items-center gap-2 text-sm">
              <Search className="w-4 h-4 text-slate-400 shrink-0" />
              <input
                value={filters.q}
                onChange={(e) => patch({ q: e.target.value })}
                placeholder={t("explore.searchPlaceholder")}
                className="w-full border border-slate-200 rounded-lg px-2 py-1.5"
                data-testid="explore-q"
              />
            </label>

            <Section
              title={t("explore.facet.skills")}
              active={filters.skills.length > 0 || filters.skillsExclude.length > 0}
              count={filters.skills.length + filters.skillsExclude.length}
              defaultOpen
            >
              <SkillPicker
                value={filters.skills.map((s) => s.key)}
                onChange={(keys) =>
                  patch({
                    skills: keys.map(
                      (key) => filters.skills.find((s) => s.key === key) ?? { key, level: null }
                    ),
                  })
                }
                placeholder={t("explore.addSkill")}
              />
              {filters.skills.length > 0 && (
                <>
                  <div className="flex flex-wrap gap-1">
                    {filters.skills.map((s) => (
                      <span
                        key={s.key}
                        className="text-xs bg-primary-50 text-primary-700 border border-primary-200 rounded-full px-2 py-0.5 flex items-center gap-1"
                        data-testid={`skill-chip-${s.key}`}
                      >
                        {skillOptions.find((o) => o.value === s.key)?.label ?? s.key}
                        <select
                          value={s.level ?? ""}
                          onChange={(e) =>
                            patch({
                              skills: filters.skills.map((entry) =>
                                entry.key === s.key
                                  ? { ...entry, level: e.target.value ? Number(e.target.value) : null }
                                  : entry
                              ),
                            })
                          }
                          className="bg-white border border-primary-200 rounded px-0.5 text-[11px] text-primary-700"
                          aria-label={t("explore.skillLevel")}
                          data-testid={`skill-level-${s.key}`}
                        >
                          <option value="">{t("explore.anyLevel")}</option>
                          {Array.from({ length: 10 }, (_, i) => (
                            <option key={i + 1} value={i + 1}>≥{i + 1}</option>
                          ))}
                        </select>
                        <button
                          onClick={() =>
                            patch({ skills: filters.skills.filter((f) => f.key !== s.key) })
                          }
                          aria-label={t("explore.removeSkill", { skill: s.key })}
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                  <select
                    value={filters.skillMode}
                    onChange={(e) => patch({ skillMode: e.target.value as "all" | "any" })}
                    className="text-xs border border-slate-200 rounded-lg px-1 py-1 w-full"
                    aria-label={t("explore.skillMatchMode")}
                  >
                    <option value="all">{t("explore.allMustMatch")}</option>
                    <option value="any">{t("explore.anyMatches")}</option>
                  </select>
                </>
              )}
              <p className="text-xs font-medium text-slate-500 pt-1">
                {t("explore.excludeSkills")}
              </p>
              <SkillPicker
                value={filters.skillsExclude}
                onChange={(keys) => patch({ skillsExclude: keys })}
                placeholder={t("explore.excludeSkillPlaceholder")}
              />
              {!active && ((facets ?? {}).skills ? Object.keys((facets ?? {}).skills) : []).length > 0 && (
                <div className="flex flex-wrap gap-1 pt-1">
                  {Object.entries((facets ?? {}).skills ?? {})
                    .slice(0, 8)
                    .map(([key, count]) => (
                      <button
                        key={key}
                        onClick={() => addSkillFilter(key)}
                        className="text-[10px] bg-slate-50 text-slate-500 border border-slate-100 px-1.5 py-0.5 rounded hover:bg-primary-50"
                      >
                        {key} · {count}
                      </button>
                    ))}
                </div>
              )}
            </Section>

            <Section title={t("explore.facet.posted")} active={!!filters.postedWithin}>
              <TriStateChips
                showCounts
                allowExclude={false}
                values={POSTED_WINDOWS.map((w) => ({
                  value: w.value,
                  label: t(w.labelKey),
                  count: (facets ?? {}).posted?.[w.value],
                  testId: `posted-${w.value}`,
                }))}
                include={filters.postedWithin ? [filters.postedWithin] : []}
                exclude={[]}
                onToggle={(value) =>
                  patch({ postedWithin: filters.postedWithin === value ? "" : value })
                }
              />
            </Section>

            <Section title={t("explore.salaryFrom")} active={!!filters.salaryMin}>
              <input
                value={filters.salaryMin}
                onChange={(e) => patch({ salaryMin: e.target.value.replace(/[^0-9]/g, "") })}
                placeholder={t("explore.salaryExample")}
                className="w-full border border-slate-200 rounded-lg px-2 py-1.5 text-sm"
                data-testid="salary-min"
              />
            </Section>

            <Section
              title={t("explore.seniority")}
              active={filters.seniority.length + filters.seniorityExclude.length > 0}
              count={filters.seniority.length + filters.seniorityExclude.length}
            >
              <TriStateChips
                showCounts
                values={Object.entries((facets ?? {}).seniority ?? {}).map(([value, count]) => ({
                  value,
                  label: t(`explore.facetValue.${value}`, { defaultValue: value }),
                  count,
                  testId: `seniority-${value}`,
                }))}
                include={filters.seniority}
                exclude={filters.seniorityExclude}
                onToggle={(value, mode) => {
                  const next = triStateToggle(
                    filters.seniority,
                    filters.seniorityExclude,
                    value,
                    mode
                  );
                  patch({ seniority: next.include, seniorityExclude: next.exclude });
                }}
              />
            </Section>

            <Section
              title={t("explore.facet.workMode")}
              active={filters.remotePolicy.length + filters.remotePolicyExclude.length > 0}
              count={filters.remotePolicy.length + filters.remotePolicyExclude.length}
            >
              <TriStateChips
                showCounts
                values={Object.entries((facets ?? {}).remote_policy ?? {}).map(([value, count]) => ({
                  value,
                  label: t(`explore.facetValue.${value}`, { defaultValue: value }),
                  count,
                  testId: `mode-${value}`,
                }))}
                include={filters.remotePolicy}
                exclude={filters.remotePolicyExclude}
                onToggle={(value, mode) => {
                  const next = triStateToggle(
                    filters.remotePolicy,
                    filters.remotePolicyExclude,
                    value,
                    mode
                  );
                  patch({ remotePolicy: next.include, remotePolicyExclude: next.exclude });
                }}
              />
            </Section>

            <Section
              title={t("explore.facet.contract")}
              active={filters.contract.length + filters.contractExclude.length > 0}
              count={filters.contract.length + filters.contractExclude.length}
            >
              <TriStateChips
                values={CONTRACT_VALUES.map((value) => ({
                  value,
                  label: t(`explore.facetValue.${value}`, { defaultValue: value.replace(/_/g, " ") }),
                  testId: `contract-${value}`,
                }))}
                include={filters.contract}
                exclude={filters.contractExclude}
                onToggle={(value, mode) => {
                  const next = triStateToggle(filters.contract, filters.contractExclude, value, mode);
                  patch({ contract: next.include, contractExclude: next.exclude });
                }}
              />
            </Section>

            <Section
              title={t("explore.facet.travel")}
              active={filters.travel.length + filters.travelExclude.length > 0}
              count={filters.travel.length + filters.travelExclude.length}
            >
              <TriStateChips
                values={TRAVEL_VALUES.map((value) => ({
                  value,
                  label: t(`explore.facetValue.${value}`, { defaultValue: value }),
                  testId: `travel-${value}`,
                }))}
                include={filters.travel}
                exclude={filters.travelExclude}
                onToggle={(value, mode) => {
                  const next = triStateToggle(filters.travel, filters.travelExclude, value, mode);
                  patch({ travel: next.include, travelExclude: next.exclude });
                }}
              />
            </Section>

            <Section
              title={t("explore.facet.schedule")}
              active={filters.schedule.length + filters.scheduleExclude.length > 0}
              count={filters.schedule.length + filters.scheduleExclude.length}
            >
              <TriStateChips
                values={SCHEDULE_VALUES.map((value) => ({
                  value,
                  label: t(`explore.facetValue.${value}`, { defaultValue: value.replace(/_/g, " ") }),
                  testId: `schedule-${value}`,
                }))}
                include={filters.schedule}
                exclude={filters.scheduleExclude}
                onToggle={(value, mode) => {
                  const next = triStateToggle(filters.schedule, filters.scheduleExclude, value, mode);
                  patch({ schedule: next.include, scheduleExclude: next.exclude });
                }}
              />
            </Section>

            <Section
              title={t("explore.facet.organization")}
              active={filters.orgs.length + filters.orgsExclude.length > 0}
              count={filters.orgs.length + filters.orgsExclude.length}
            >
              <OrgPicker
                value={filters.orgs}
                onChange={(names) => patch({ orgs: names })}
                placeholder={t("explore.orgPlaceholder")}
              />
              <p className="text-xs font-medium text-slate-500 pt-1">
                {t("explore.excludeOrganizations")}
              </p>
              <OrgPicker
                value={filters.orgsExclude}
                onChange={(names) => patch({ orgsExclude: names })}
                placeholder={t("explore.excludeOrgPlaceholder")}
              />
            </Section>

            <Section
              title={t("explore.facet.sources")}
              active={filters.source.length + filters.sourceExclude.length > 0}
              count={filters.source.length + filters.sourceExclude.length}
            >
              {sources.length === 0 ? (
                <p className="text-xs text-slate-400">{t("explore.noSources")}</p>
              ) : (
                <TriStateChips
                  showCounts
                  values={sources.map((s) => ({
                    value: s.key,
                    label: s.key,
                    count: facetCount("source", s.key) ?? s.open_postings,
                    testId: `source-${s.key}`,
                  }))}
                  include={filters.source}
                  exclude={filters.sourceExclude}
                  onToggle={(value, mode) => {
                    const next = triStateToggle(filters.source, filters.sourceExclude, value, mode);
                    patch({ source: next.include, sourceExclude: next.exclude });
                  }}
                />
              )}
            </Section>

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
              onOpen={(item) => navigate(`/postings/${item.ref}`)}
              onChanged={() => load(filters, false)}
            />
          ))}
          {cursor && !radarActive && (
            <div ref={sentinelRef} className="h-px" data-testid="load-more-sentinel" />
          )}
          {loadingMore && (
            <div className="flex justify-center py-4" data-testid="loading-more">
              <Spinner size="lg" label={t("explore.loadingMore")} />
            </div>
          )}
          {radarActive && (
            <button
              onClick={clearRadar}
              className="text-sm text-primary-700 hover:underline"
              data-testid="radar-clear-inline"
            >
              {t("explore.radarClear")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
