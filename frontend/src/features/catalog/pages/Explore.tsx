import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useNavigationType, useSearchParams, useLocation } from "react-router-dom";
import { ArrowUpDown, Radar, Sparkles, X } from "lucide-react";

import { explorePostings, fetchPostingSources, smartSearch } from "@/api/postings";
import { fetchRadar, previewRadar } from "@/api/radar";
import { apiDetail } from "@/api/client";
import type { ExploreParams } from "@/types";
import { fetchSkillOntology } from "@/api/skills";
import { PostingCard } from "@/features/postings/components/PostingCard";
import { PostingsStatsRail } from "@/components/stats/StatsRail";
import { PresetBar } from "@/features/postings/components/postings/PresetBar";
import { EmptyState, SearchableDropdown, Spinner } from "@/components/ui";
import { UndoNotice } from "@neuronection/assistant-ui";
import { useInfiniteScroll } from "@/hooks/useInfiniteScroll";
import { isListReturn, rememberListSearch } from "@/lib/listReturn";
import {
  peekExploreList,
  rememberExploreList,
  type ExploreListSnapshot,
} from "@/features/catalog/exploreListCache";
import type { ExploreFacets, PostingSourceInfo } from "@/types/wire";
import type { PostingOut } from "@/types/wire";
import { SkillPicker } from "@/features/postings/components/postings/SkillPicker";
import { OrgPicker } from "@/features/postings/components/postings/OrgPicker";
import { useProfilesStore } from "@/stores/profilesStore";
import { useRetrievalDebugStore } from "@/stores/retrievalDebugStore";
import { Section, TriStateChips, triStateToggle } from "@/components/filters/filterBits";
import { FilterRail, FilterRailSearch } from "@/components/filters/FilterRail";
import {
  applyCardFilter,
  filterStateOf,
  type CardFilterApi,
  type CardFilterTarget,
} from "@/features/postings/components/postings/cardFilterMenu";
import {
  CONTRACT_VALUES,
  POSTED_WINDOWS,
  SCHEDULE_VALUES,
  SORT_OPTIONS,
  TRAVEL_VALUES,
  countActive,
  parseFilters,
  toParams,
  toSearchParams,
  type Filters,
} from "@/features/catalog/exploreParams";

const EMPTY_FACETS: ExploreFacets = {};

export function Explore() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => parseFilters(searchParams), [searchParams]);
  const profileEpoch = useProfilesStore((state) => state.epoch);
  const plainKey = useMemo(() => toSearchParams(filters).toString(), [filters]);
  const searchKey = `${profileEpoch}|${plainKey}`;
  const navigationType = useNavigationType();
  const location = useLocation();
  const restorable = navigationType === "POP" || isListReturn(location.state);
  const restoredRef = useRef<ExploreListSnapshot | null | undefined>(undefined);
  if (restoredRef.current === undefined) {
    restoredRef.current = restorable ? peekExploreList(searchKey) : null;
  }
  const restored = restoredRef.current;
  const [items, setItems] = useState<PostingOut[]>(() => restored?.items ?? []);
  const retrievalDebugEnabled = useRetrievalDebugStore((state) => state.enabled);
  const loadRetrievalStatuses = useRetrievalDebugStore((state) => state.load);
  const [total, setTotal] = useState(() => restored?.total ?? 0);
  const [facets, setFacets] = useState<ExploreFacets>(
    () => restored?.facets ?? EMPTY_FACETS
  );
  const [cursor, setCursor] = useState<string | null>(
    () => restored?.nextCursor ?? null
  );
  const [sources, setSources] = useState<PostingSourceInfo[]>([]);
  const [skillOptions, setSkillOptions] = useState<{ value: string; label: string }[]>([]);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const [savedNote, setSavedNote] = useState("");
  const [radarActive, setRadarActive] = useState(false);
  const [smartQuery, setSmartQuery] = useState("");
  const [smartBusy, setSmartBusy] = useState(false);
  const [smartApplied, setSmartApplied] = useState<{
    interpreted: string;
    keys: string[];
  } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const filtersRef = useRef(filters);
  const itemsRef = useRef<PostingOut[]>(items);

  const paramsFrom = useCallback(
    (current: Filters, nextCursor?: string | null): ExploreParams => {
      const params: ExploreParams = { ...toParams(current), sort: current.sort, limit: 20 };
      if (nextCursor) params.cursor = nextCursor;
      return params;
    },
    []
  );

  const load = useCallback(
    (current: Filters, append: boolean) => {
      setError("");
      void explorePostings(paramsFrom(current, append ? cursor : null))
        .then((response) => {
          const merged = append
            ? [...itemsRef.current, ...response.items]
            : response.items;
          setItems(merged);
          itemsRef.current = merged;
          setTotal(response.total);
          setFacets(response.facets ?? {});
          setCursor(response.next_cursor ?? null);
          rememberExploreList(
            `${profileEpoch}|${toSearchParams(current).toString()}`,
            {
              items: merged,
              total: response.total,
              facets: response.facets ?? {},
              nextCursor: response.next_cursor ?? null,
            }
          );
        })
        .catch((err) => setError(String(err)));
    },
    [cursor, paramsFrom, profileEpoch]
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

  const restoredForRef = useRef<Filters | null>(null);
  useEffect(() => {
    if (restoredRef.current && restoredForRef.current === null) {
      restoredForRef.current = filters;
      return;
    }
    if (restoredForRef.current === filters) return;
    setRadarActive(false);
    setCursor(null);
    load(filters, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  useEffect(() => {
    rememberListSearch("/postings", plainKey);
  }, [plainKey]);

  useEffect(() => {
    if (!retrievalDebugEnabled || items.length === 0) return;
    void loadRetrievalStatuses(items.map((item) => String(item.id)));
  }, [items, retrievalDebugEnabled, loadRetrievalStatuses]);

  const patch = useCallback(
    (update: Partial<Filters>) => {
      setSearchParams(toSearchParams({ ...filters, ...update }), { replace: true });
    },
    [filters, setSearchParams]
  );

  const [undoExclude, setUndoExclude] = useState<{
    message: string;
    undo: () => void;
  } | null>(null);

  const cardFilterMenu = useMemo<CardFilterApi | undefined>(() => {
    if (radarActive) return undefined;
    return {
      stateOf: (axis, value) => filterStateOf(filters, axis, value),
      apply: (target: CardFilterTarget, mode) => {
        const prev = filterStateOf(filters, target.axis, target.value);
        patch(applyCardFilter(filters, target, mode));
        if (mode === "exclude") {
          setUndoExclude({
            message: t("filters.menu.excludedNotice", { value: target.label }),
            undo: () =>
              patch(applyCardFilter(filters, target, prev ?? "clear")),
          });
        } else if (mode !== "clear") {
          setUndoExclude(null);
        }
      },
    };
  }, [filters, patch, radarActive, t]);

  const resetFilters = useCallback(() => {
    setSearchParams(new URLSearchParams(), { replace: true });
  }, [setSearchParams]);

  useEffect(() => {
    filtersRef.current = filters;
  }, [filters]);

  useEffect(() => {
    const canonical = toSearchParams(parseFilters(searchParams)).toString();
    if (canonical !== searchParams.toString()) {
      setSearchParams(new URLSearchParams(canonical), { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadMore = useCallback(() => {
    if (!cursor || radarActive) return undefined;
    const requestFilters = filters;
    setLoadingMore(true);
    setError("");
    return explorePostings(paramsFrom(requestFilters, cursor))
      .then((response) => {
        // a filter change that landed mid-flight re-owns the list —
        // the stale page is dropped, never appended to it
        if (requestFilters !== filtersRef.current) return;
        const merged = [...itemsRef.current, ...response.items];
        setItems(merged);
        itemsRef.current = merged;
        setTotal(response.total);
        setFacets(response.facets ?? {});
        setCursor(response.next_cursor ?? null);
        rememberExploreList(
          `${profileEpoch}|${toSearchParams(requestFilters).toString()}`,
          {
            items: merged,
            total: response.total,
            facets: response.facets ?? {},
            nextCursor: response.next_cursor ?? null,
          }
        );
      })
      .catch((err) => setError(String(err)))
      .finally(() => setLoadingMore(false));
  }, [cursor, filters, paramsFrom, radarActive, profileEpoch]);

  const sentinelRef = useInfiniteScroll(loadMore, !!cursor && !radarActive);

  const addSkillFilter = (key: string) => {
    if (!key || filters.skills.some((s) => s.key === key)) return;
    patch({ skills: [...filters.skills, { key, level: null }] });
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
      itemsRef.current = response.items;
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
    resetFilters();
    setCursor(null);
  };

  const runSmartSearch = async () => {
    const query = smartQuery.trim();
    if (!query || smartBusy) return;
    setSmartBusy(true);
    setError("");
    try {
      const response = await smartSearch(query);
      const next: Filters = { ...filters };
      const raw = response.filters as Record<string, unknown>;
      const keys: string[] = [];
      const list = (value: unknown) =>
        Array.isArray(value) ? value.map((entry) => String(entry)) : [];
      if ("seniority" in raw) {
        next.seniority = list(raw.seniority);
        keys.push("seniority");
      }
      if ("remote_policy" in raw) {
        next.remotePolicy = list(raw.remote_policy);
        keys.push("remote_policy");
      }
      if ("posted_within" in raw) {
        next.postedWithin = String(raw.posted_within ?? "");
        keys.push("posted_within");
      }
      if ("salary_min" in raw) {
        next.salaryMin = raw.salary_min != null ? String(raw.salary_min) : "";
        keys.push("salary_min");
      }
      if ("city" in raw) {
        next.city = String(raw.city ?? "");
        keys.push("city");
      }
      if ("country" in raw) {
        next.country = String(raw.country ?? "");
        keys.push("country");
      }
      if ("employment_type" in raw) {
        next.employmentType = list(raw.employment_type);
        keys.push("employment_type");
      }
      if ("mapped_family" in raw) {
        next.mappedFamily = list(raw.mapped_family);
        keys.push("mapped_family");
      }
      if ("skills" in raw) {
        const value = String(raw.skills ?? "");
        next.skills = value
          .split(",")
          .filter(Boolean)
          .map((key) => ({ key, level: null }));
        keys.push("skills");
      }
      setSearchParams(toSearchParams(next), { replace: true });
      setSmartApplied({ interpreted: response.interpreted, keys });
    } catch (err) {
      setError(String(err));
    } finally {
      setSmartBusy(false);
    }
  };

  const removeSmartKey = (key: string) => {
    const next: Filters = { ...filters };
    if (key === "seniority") next.seniority = [];
    else if (key === "remote_policy") next.remotePolicy = [];
    else if (key === "posted_within") next.postedWithin = "";
    else if (key === "salary_min") next.salaryMin = "";
    else if (key === "city") next.city = "";
    else if (key === "country") next.country = "";
    else if (key === "employment_type") next.employmentType = [];
    else if (key === "mapped_family") next.mappedFamily = [];
    else if (key === "skills") next.skills = [];
    setSmartApplied((current) =>
      current
        ? { interpreted: current.interpreted, keys: current.keys.filter((k) => k !== key) }
        : current
    );
    setSearchParams(toSearchParams(next), { replace: true });
  };

  const activeCount = countActive(filters);
  const active = activeCount > 0;

  const facetCount = (group: string, key: string): number | undefined =>
    (facets ?? {})[group]?.[key];

  const sortOptions = SORT_OPTIONS.filter(
    (option) => option.value !== "relevance" || filters.q.trim().length > 0
  ).map((option) => ({ value: option.value, label: t(option.labelKey) }));
  const jobValues = Array.from(
    new Set([...Object.keys(facets?.job ?? {}), ...filters.job])
  ).map((code) => ({
    value: code,
    label: code,
    count: facets?.job?.[code] ?? 0,
    testId: `job-${code}`,
  }));

  return (
    <div className="ca-stats-page space-y-6" data-testid="explore">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="min-w-0 flex-1 text-sm text-slate-500">
          {radarActive ? t("explore.radarActive") : t("explore.intro")}
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
        </div>
      </div>
      {savedNote && <p className="text-sm text-emerald-600" data-testid="saved-note">{savedNote}</p>}

      <PresetBar
        filters={filters}
        total={total}
        onApply={(next) => setSearchParams(toSearchParams(next), { replace: true })}
      />

      <div className="ca-stats-cols">
        <FilterRail
          title={t("filters.title")}
          activeCount={activeCount}
          onClear={resetFilters}
          countTestId="explore-filter-count"
          clearTestId="clear-filters"
          asideTestId="explore-filters"
          testId="explore-filter-rail"
        >
          <FilterRailSearch
            value={filters.q}
            onChange={(q) =>
              patch({
                q,
                ...(filters.sort === "relevance" && !q.trim() ? { sort: "fit" } : {}),
              })
            }
            placeholder={t("explore.searchPlaceholder")}
            testId="explore-q"
          />

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
                        className="flex items-center gap-1 rounded-full border border-[var(--as-accent)] bg-[var(--as-muted)] px-2 py-0.5 text-xs text-[var(--as-accent)]"
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
                          className="rounded border border-[var(--as-border)] bg-[var(--as-surface)] px-0.5 text-[11px] text-[var(--as-fg)]"
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
                    className="w-full rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] px-1 py-1 text-xs text-[var(--as-fg)]"
                    aria-label={t("explore.skillMatchMode")}
                  >
                    <option value="all">{t("explore.allMustMatch")}</option>
                    <option value="any">{t("explore.anyMatches")}</option>
                  </select>
                </>
              )}
              <p className="pt-1 text-xs font-medium text-[var(--as-muted-fg)]">
                {t("explore.excludeSkills")}
              </p>
              <SkillPicker
                exclude
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
                        className="rounded border border-[var(--as-border)] bg-[var(--as-muted)] px-1.5 py-0.5 text-[10px] text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-fg)]"
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
                onToggle={(value, mode) =>
                  patch({ postedWithin: mode === "clear" ? "" : value })
                }
              />
            </Section>

            <Section title={t("explore.salaryFrom")} active={!!filters.salaryMin}>
              <input
                value={filters.salaryMin}
                onChange={(e) => patch({ salaryMin: e.target.value.replace(/[^0-9]/g, "") })}
                placeholder={t("explore.salaryExample")}
                className="w-full rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1.5 text-sm text-[var(--as-fg)]"
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
              <p className="pt-1 text-xs font-medium text-[var(--as-muted-fg)]">
                {t("explore.excludeOrganizations")}
              </p>
              <OrgPicker
                exclude
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
                <p className="text-xs text-[var(--as-muted-fg)]">{t("explore.noSources")}</p>
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

            <Section
              title={t("explore.facet.job")}
              active={filters.job.length > 0}
              count={filters.job.length}
            >
              <TriStateChips
                showCounts
                allowExclude={false}
                values={jobValues}
                include={filters.job}
                exclude={[]}
                onToggle={(value, mode) =>
                  patch({
                    job:
                      mode === "clear"
                        ? filters.job.filter((code) => code !== value)
                        : [value],
                  })
                }
              />
            </Section>

            <label className="flex items-center justify-between text-xs text-[var(--as-muted-fg)]">
              <span>{t("explore.deepExtractedOnly")}</span>
              <input
                type="checkbox"
                checked={filters.extractedOnly}
                onChange={(e) => patch({ extractedOnly: e.target.checked })}
                data-testid="extracted-only"
              />
            </label>
            <label className="flex items-center justify-between text-xs text-[var(--as-muted-fg)]">
              <span>{t("explore.savedOnly")}</span>
              <input
                type="checkbox"
                checked={filters.saved}
                onChange={(e) => patch({ saved: e.target.checked })}
                data-testid="saved-only"
              />
            </label>
            <label className="flex items-center justify-between text-xs text-[var(--as-muted-fg)]">
              <span title={t("explore.hideSeenTitle")}>{t("explore.hideSeen")}</span>
              <input
                type="checkbox"
                checked={filters.seenExclude}
                onChange={(e) => patch({ seenExclude: e.target.checked })}
                data-testid="seen-exclude"
              />
            </label>
        </FilterRail>

        <div className="flex-1 space-y-3">
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              void runSmartSearch();
            }}
            data-testid="smart-search"
          >
            <Sparkles aria-hidden className="h-3.5 w-3.5 text-slate-400" />
            <input
              value={smartQuery}
              onChange={(e) => setSmartQuery(e.target.value)}
              placeholder={t("explore.smartSearchPlaceholder")}
              className="flex-1 min-w-[12rem] border border-slate-200 rounded-lg px-2 py-1.5 text-xs"
              aria-label={t("explore.smartSearchPlaceholder")}
              data-testid="smart-search-input"
            />
            <button
              type="submit"
              disabled={smartBusy || !smartQuery.trim()}
              className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 disabled:opacity-50"
              data-testid="smart-search-submit"
            >
              {t("explore.smartSearchSubmit")}
            </button>
          </form>
          {smartApplied && (
            <div className="flex flex-wrap items-center gap-1 text-[10px] text-slate-500">
              <span>{t("explore.interpretedAs")}</span>
              {smartApplied.interpreted && <span data-testid="smart-interpreted">{smartApplied.interpreted}</span>}
              {smartApplied.keys.map((key) => (
                <span
                  key={key}
                  className="bg-primary-50 text-primary-700 border border-primary-200 rounded-full px-2 py-0.5 flex items-center gap-1"
                  data-testid={`smart-chip-${key}`}
                >
                  {key}
                  <button
                    onClick={() => removeSmartKey(key)}
                    aria-label={t("explore.removeInterpreted", { key })}
                    data-testid={`smart-chip-remove-${key}`}
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
              {smartApplied.keys.length === 0 && (
                <button
                  onClick={() => setSmartApplied(null)}
                  className="text-slate-400 hover:text-slate-600"
                  aria-label={t("explore.dismissInterpreted")}
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-slate-500" data-testid="explore-result-count">
              {total ? t("explore.matching", { count: total }) : ""}
            </p>
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <ArrowUpDown aria-hidden className="h-3.5 w-3.5" />
              <span>{t("explore.sortBy")}</span>
              <div
                className="w-44"
                data-testid="explore-sort-wrap"
                title={filters.sort === "smart" ? t("explore.smartChipInfo") : undefined}
              >
                <SearchableDropdown
                  options={sortOptions}
                  value={filters.sort}
                  onChange={(value) => patch({ sort: value })}
                  label={t("explore.sortBy")}
                  hideLabel
                />
              </div>
            </div>
          </div>
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
              smartSort={filters.sort === "smart"}
              filterMenu={cardFilterMenu}
              showRetrievalState
              onOpen={(item) => navigate(`/postings/${item.ref}`)}
              onChanged={() => load(filters, false)}
            />
          ))}
          {undoExclude && (
            <div className="fixed bottom-6 left-1/2 z-[var(--as-z-modal)] -translate-x-1/2" data-testid="explore-undo-exclude">
              <UndoNotice
                message={undoExclude.message}
                actionLabel={t("common.undo")}
                duration={8000}
                onUndo={() => {
                  undoExclude.undo();
                  setUndoExclude(null);
                }}
                onDismiss={() => setUndoExclude(null)}
              />
            </div>
          )}
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

        <PostingsStatsRail
          onPostedWithin={(value) =>
            patch({
              postedWithin: filters.postedWithin === value ? "" : value,
            })
          }
          onSkill={addSkillFilter}
          onSource={(key) => {
            const next = triStateToggle(filters.source, filters.sourceExclude, key, "include");
            patch({ source: next.include, sourceExclude: next.exclude });
          }}
        />
      </div>
    </div>
  );
}
