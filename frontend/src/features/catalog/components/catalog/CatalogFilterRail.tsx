/**
 * The catalog filter rail (plan 190): the `/postings` grammar over job
 * axes — tri-state chips with facet counts, a skill picker with levels and
 * any/all, salary/experience bounds and the open-roles flag. Pure
 * presentation: URL state lives in `CatalogTree`.
 */

import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import {
  FacetChip,
  FilterRail,
  FilterSection,
} from "@neuronection/assistant-ui/filters";

import { FilterRailSearch } from "@/components/filters/FilterRailSearch";
import { SkillPicker } from "@/features/postings/components/postings/SkillPicker";
import {
  CONTRACT_VALUES,
  DEMAND_VALUES,
  EDUCATION_VALUES,
  ENVIRONMENT_VALUES,
  SCHEDULE_VALUES,
  TRAVEL_VALUES,
  countActiveCatalogFilters,
  type CatalogFilters,
} from "@/features/catalog/catalogParams";
import type { ContainerBand } from "@/hooks/useContainerBand";
import type { CountsState, FacetValue, TriStateMode } from "@/lib/filterFacets";
import {
  facetLabels,
  facetOptions,
  multiValue,
  railLabels,
  railLayout,
  singleValue,
  triStateToggle,
} from "@/lib/filterFacets";
import type { JobFacets } from "@/types/wire";
import type { JobFamilyNode } from "@/types";

function flattenFamilies(nodes: JobFamilyNode[], depth = 0): { node: JobFamilyNode; depth: number }[] {
  return nodes.flatMap((node) => [
    { node, depth },
    ...flattenFamilies(node.children, depth + 1),
  ]);
}

function facetCount(facets: JobFacets, axis: string, value: string): number | undefined {
  return facets[axis]?.[value];
}

function selectedValues(...groups: string[][]): string[] {
  return Array.from(new Set(groups.flat()));
}

export function CatalogFilterRail({
  filters,
  facets,
  families,
  band,
  counts = "ready",
  footer,
  onChange,
  onClear,
}: {
  filters: CatalogFilters;
  facets: JobFacets;
  families: JobFamilyNode[];
  band?: ContainerBand;
  /** Whether the facet map on screen is still the last successful response. */
  counts?: CountsState;
  /**
   * The compact sheet's host footer, carrying a real result total. Omit it
   * while the last load is stale (the total then describes a query that did
   * not run): the sheet falls back to the library `Done`, never `Show N`.
   */
  footer?: (close: () => void) => ReactNode;
  onChange: (update: Partial<CatalogFilters>) => void;
  onClear: () => void;
}) {
  const { t } = useTranslation();
  const valueLabel = (value: string) =>
    t(`catalog.facetValue.${value}`, { defaultValue: value.replace(/_/g, " ") });
  const toggle = (
    axis: "education" | "demand" | "contract" | "schedule" | "travel" | "environment",
    include: string[],
    exclude: string[],
    value: string,
    mode: TriStateMode
  ) => {
    const next = triStateToggle(include, exclude, value, mode);
    onChange({ [axis]: next.include, [`${axis}Exclude`]: next.exclude } as Partial<CatalogFilters>);
  };
  const enumChips = (axis: "education" | "demand" | "contract" | "schedule" | "travel" | "environment", values: readonly string[]): FacetValue[] =>
    values.map((value) => ({
      value,
      label: valueLabel(value),
      count: facetCount(facets, axis, value),
    }));

  const familyChips = flattenFamilies(families).map(({ node, depth }) => ({
    value: node.key,
    label: `${"\u00a0".repeat(depth * 2)}${node.label}`,
    count: facetCount(facets, "family", node.key),
  }));

  const interestValues = selectedValues(
    Object.keys(facets.interests ?? {}),
    filters.interests,
    filters.interestsExclude
  );

  const activeCount = countActiveCatalogFilters(filters);
  const labels = facetLabels(t);
  /** One inline facet row on the shared chip; `id` is the option test-id prefix. */
  const facetChip = (
    id: string,
    label: string,
    values: FacetValue[],
    include: string[],
    exclude: string[],
    onToggleValue: (value: string, mode: TriStateMode) => void,
    { allowExclude = true, single = false }: { allowExclude?: boolean; single?: boolean } = {}
  ) => {
    const allow = allowExclude && !single;
    return (
      <FacetChip
        facet={{
          id,
          label,
          kind: single ? "single" : "multi",
          allowExclude: allow,
          countsState: counts,
          options: facetOptions(values, { include, exclude }),
        }}
        value={single ? singleValue(include[0] ?? null) : multiValue(include, exclude)}
        variant="inline"
        showActivePills={false}
        labels={labels}
        onToggleOption={(value, action) => {
          if (value === null) return;
          onToggleValue(value, action);
        }}
        testId={`${id}-facet`}
        optionTestId={(value) => `${id}-${value ?? "not-recorded"}`}
      />
    );
  };

  return (
    <FilterRail
      layout={railLayout(band)}
      title={t("filters.title")}
      labels={railLabels(t)}
      activeCount={activeCount === 0 ? undefined : activeCount}
      onClear={activeCount === 0 ? undefined : onClear}
      footer={footer}
      className="ca-stats-rail"
      data-testid="catalog-filter-aside"
      search={
        <FilterRailSearch
          value={filters.q}
          onChange={(q) => onChange({ q })}
          placeholder={t("catalog.searchPlaceholder")}
          testId="catalog-search"
        />
      }
    >
      <FilterSection
        title={t("catalog.filters.skills")}
        active={filters.skills.length + filters.skillsExclude.length + (filters.minLevel ? 1 : 0) > 0}
        defaultOpen
      >
        <SkillPicker
          value={filters.skills.map((skill) => skill.key)}
          onChange={(keys) =>
            onChange({
              skills: keys.map(
                (key) => filters.skills.find((skill) => skill.key === key) ?? { key, level: null }
              ),
            })
          }
          placeholder={t("catalog.filters.addSkill")}
        />
        {filters.skills.length > 0 ? (
          <>
            <div className="flex flex-wrap gap-1">
              {filters.skills.map((skill) => (
                <span
                  key={skill.key}
                  className="flex items-center gap-1 rounded-full border border-[var(--as-primary)] bg-[var(--as-muted)] px-2 py-0.5 text-xs"
                  data-testid={`catalog-skill-${skill.key}`}
                >
                  {skill.key}
                  <select
                    value={skill.level ?? ""}
                    onChange={(event) =>
                      onChange({
                        skills: filters.skills.map((entry) =>
                          entry.key === skill.key
                            ? {
                                ...entry,
                                level: event.target.value ? Number(event.target.value) : null,
                              }
                            : entry
                        ),
                      })
                    }
                    className="rounded border border-[var(--as-border)] bg-[var(--as-surface)] px-0.5 text-[11px]"
                    aria-label={t("catalog.filters.skillLevel")}
                    data-testid={`catalog-skill-level-${skill.key}`}
                  >
                    <option value="">{t("catalog.filters.anyLevel")}</option>
                    {Array.from({ length: 10 }, (_, index) => (
                      <option key={index + 1} value={index + 1}>
                        ≥{index + 1}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() =>
                      onChange({ skills: filters.skills.filter((entry) => entry.key !== skill.key) })
                    }
                    aria-label={t("catalog.filters.removeSkill", { skill: skill.key })}
                    data-testid={`catalog-skill-remove-${skill.key}`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
            <select
              value={filters.skillMode}
              onChange={(event) => onChange({ skillMode: event.target.value as "all" | "any" })}
              className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-1 py-1 text-xs"
              aria-label={t("catalog.filters.skillMatchMode")}
              data-testid="catalog-skill-mode"
            >
              <option value="all">{t("catalog.filters.allMustMatch")}</option>
              <option value="any">{t("catalog.filters.anyMatches")}</option>
            </select>
          </>
        ) : null}
        <label className="flex items-center gap-2 text-xs text-[var(--as-muted-fg)]">
          {t("catalog.filters.minLevel")}
          <select
            value={filters.minLevel ?? ""}
            onChange={(event) =>
              onChange({ minLevel: event.target.value ? Number(event.target.value) : null })
            }
            className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-1 py-1"
            data-testid="catalog-min-level"
          >
            <option value="">{t("catalog.filters.anyLevel")}</option>
            {Array.from({ length: 10 }, (_, index) => (
              <option key={index + 1} value={index + 1}>
                ≥{index + 1}
              </option>
            ))}
          </select>
        </label>
        <p className="pt-1 text-xs font-medium text-[var(--as-muted-fg)]">
          {t("catalog.filters.excludeSkills")}
        </p>
        <SkillPicker
          exclude
          value={filters.skillsExclude}
          onChange={(keys) => onChange({ skillsExclude: keys })}
          placeholder={t("catalog.filters.excludeSkillPlaceholder")}
        />
        {Object.keys(facets.skills ?? {}).length > 0 ? (
          <div className="flex flex-wrap gap-1 pt-1">
            {Object.entries(facets.skills ?? {})
              .slice(0, 8)
              .map(([key, count]) => (
                <button
                  key={key}
                  type="button"
                  disabled={filters.skills.some((skill) => skill.key === key)}
                  onClick={() =>
                    onChange({ skills: [...filters.skills, { key, level: null }] })
                  }
                  className="rounded border border-[var(--as-border)] bg-[var(--as-muted)] px-1.5 py-0.5 text-[11px] text-[var(--as-muted-fg)] disabled:opacity-40"
                  data-testid={`catalog-skill-suggestion-${key}`}
                >
                  {key} · {count}
                </button>
              ))}
          </div>
        ) : null}
      </FilterSection>

      <FilterSection
        title={t("catalog.filters.family")}
        active={filters.family !== ""}
        defaultOpen
      >
        {facetChip(
          "catalog-family",
          t("catalog.filters.family"),
          familyChips,
          filters.family ? [filters.family] : [],
          [],
          (value, mode) => onChange({ family: mode === "clear" ? "" : value }),
          { single: true }
        )}
      </FilterSection>

      <FilterSection
        title={t("catalog.filters.interests")}
        active={filters.interests.length + filters.interestsExclude.length > 0}
      >
        {facetChip(
          "catalog-interest",
          t("catalog.filters.interests"),
          interestValues.map((value) => ({
            value,
            label: value,
            count: facetCount(facets, "interests", value),
          })),
          filters.interests,
          filters.interestsExclude,
          (value, mode) => {
            const next = triStateToggle(
              filters.interests,
              filters.interestsExclude,
              value,
              mode
            );
            onChange({ interests: next.include, interestsExclude: next.exclude });
          }
        )}
      </FilterSection>

      <FilterSection
        title={t("catalog.filters.education")}
        active={
          filters.education.length + filters.educationExclude.length + (filters.educationMin ? 1 : 0) >
          0
        }
      >
        {facetChip(
          "catalog-education",
          t("catalog.filters.education"),
          enumChips("education", EDUCATION_VALUES),
          filters.education,
          filters.educationExclude,
          (value, mode) =>
            toggle("education", filters.education, filters.educationExclude, value, mode)
        )}
        <label className="flex items-center gap-2 text-xs text-[var(--as-muted-fg)]">
          {t("catalog.filters.educationMin")}
          <select
            value={filters.educationMin}
            onChange={(event) => onChange({ educationMin: event.target.value })}
            className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-1 py-1"
            data-testid="catalog-education-min"
          >
            <option value="">{t("catalog.filters.anyLevel")}</option>
            {EDUCATION_VALUES.map((value) => (
              <option key={value} value={value}>
                {valueLabel(value)}
              </option>
            ))}
          </select>
        </label>
      </FilterSection>

      <FilterSection
        title={t("catalog.filters.demand")}
        active={filters.demand.length + filters.demandExclude.length > 0}
      >
        {facetChip(
          "catalog-demand",
          t("catalog.filters.demand"),
          enumChips("demand", DEMAND_VALUES),
          filters.demand,
          filters.demandExclude,
          (value, mode) =>
            toggle("demand", filters.demand, filters.demandExclude, value, mode)
        )}
      </FilterSection>

      <FilterSection
        title={t("catalog.filters.salary")}
        active={filters.salaryMin !== "" || filters.salaryMax !== ""}
      >
        <div className="flex items-center gap-2">
          <input
            value={filters.salaryMin}
            onChange={(event) =>
              onChange({ salaryMin: event.target.value.replace(/[^0-9]/g, "") })
            }
            inputMode="numeric"
            placeholder={t("catalog.filters.salaryMin")}
            className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-sm"
            data-testid="catalog-salary-min"
          />
          <span className="text-[var(--as-muted-fg)]">–</span>
          <input
            value={filters.salaryMax}
            onChange={(event) =>
              onChange({ salaryMax: event.target.value.replace(/[^0-9]/g, "") })
            }
            inputMode="numeric"
            placeholder={t("catalog.filters.salaryMax")}
            className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-sm"
            data-testid="catalog-salary-max"
          />
        </div>
      </FilterSection>

      <FilterSection
        title={t("catalog.filters.contract")}
        active={filters.contract.length + filters.contractExclude.length > 0}
      >
        {facetChip(
          "catalog-contract",
          t("catalog.filters.contract"),
          enumChips("contract", CONTRACT_VALUES),
          filters.contract,
          filters.contractExclude,
          (value, mode) =>
            toggle("contract", filters.contract, filters.contractExclude, value, mode)
        )}
      </FilterSection>

      <FilterSection
        title={t("catalog.filters.schedule")}
        active={filters.schedule.length + filters.scheduleExclude.length > 0}
      >
        {facetChip(
          "catalog-schedule",
          t("catalog.filters.schedule"),
          enumChips("schedule", SCHEDULE_VALUES),
          filters.schedule,
          filters.scheduleExclude,
          (value, mode) =>
            toggle("schedule", filters.schedule, filters.scheduleExclude, value, mode)
        )}
      </FilterSection>

      <FilterSection
        title={t("catalog.filters.travel")}
        active={filters.travel.length + filters.travelExclude.length > 0}
      >
        {facetChip(
          "catalog-travel",
          t("catalog.filters.travel"),
          enumChips("travel", TRAVEL_VALUES),
          filters.travel,
          filters.travelExclude,
          (value, mode) =>
            toggle("travel", filters.travel, filters.travelExclude, value, mode)
        )}
      </FilterSection>

      <FilterSection
        title={t("catalog.filters.experience")}
        active={filters.experienceMax !== ""}
      >
        <label className="flex items-center gap-2 text-xs text-[var(--as-muted-fg)]">
          {t("catalog.filters.experienceMax")}
          <input
            value={filters.experienceMax}
            onChange={(event) =>
              onChange({ experienceMax: event.target.value.replace(/[^0-9]/g, "") })
            }
            inputMode="numeric"
            className="w-20 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-sm"
            data-testid="catalog-experience-max"
          />
        </label>
      </FilterSection>

      <FilterSection
        title={t("catalog.filters.environment")}
        active={filters.environment.length + filters.environmentExclude.length > 0}
      >
        {facetChip(
          "catalog-environment",
          t("catalog.filters.environment"),
          enumChips("environment", ENVIRONMENT_VALUES),
          filters.environment,
          filters.environmentExclude,
          (value, mode) =>
            toggle("environment", filters.environment, filters.environmentExclude, value, mode)
        )}
      </FilterSection>

      <FilterSection
        title={t("catalog.filters.roles")}
        active={filters.hasRoles !== null}
      >
        <button
          type="button"
          onClick={() =>
            onChange({
              hasRoles:
                filters.hasRoles === null ? true : filters.hasRoles ? false : null,
            })
          }
          data-state={
            filters.hasRoles === null ? undefined : filters.hasRoles ? "include" : "exclude"
          }
          aria-pressed={filters.hasRoles !== null}
          className={`rounded-full border px-2.5 py-1 text-xs ${
            filters.hasRoles === true
              ? "border-[var(--as-primary)] bg-[var(--as-primary)] text-[var(--as-primary-fg)]"
              : filters.hasRoles === false
                ? "border-[var(--as-warning)] bg-[var(--as-muted)] text-[var(--as-warning)]"
                : "border-[var(--as-border)] text-[var(--as-muted-fg)]"
          }`}
          data-testid="catalog-has-roles"
        >
          {filters.hasRoles === null
            ? t("catalog.filters.rolesAny")
            : filters.hasRoles
              ? t("catalog.filters.rolesHas")
              : t("catalog.filters.rolesNone")}
        </button>
      </FilterSection>
    </FilterRail>
  );
}
