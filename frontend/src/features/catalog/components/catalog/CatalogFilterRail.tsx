/**
 * The catalog filter rail (plan 190): the `/postings` grammar over job
 * axes — tri-state chips with facet counts, a skill picker with levels and
 * any/all, salary/experience bounds and the open-roles flag. Pure
 * presentation: URL state lives in `CatalogTree`.
 */

import { useTranslation } from "react-i18next";
import { X } from "lucide-react";

import {
  Section,
  TriStateChips,
  triStateToggle,
  type TriStateMode,
} from "@/components/filters/filterBits";
import { SkillPicker } from "@/features/postings/components/postings/SkillPicker";
import {
  CONTRACT_VALUES,
  DEMAND_VALUES,
  EDUCATION_VALUES,
  ENVIRONMENT_VALUES,
  SCHEDULE_VALUES,
  TRAVEL_VALUES,
  type CatalogFilters,
} from "@/features/catalog/catalogParams";
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
  onChange,
}: {
  filters: CatalogFilters;
  facets: JobFacets;
  families: JobFamilyNode[];
  onChange: (update: Partial<CatalogFilters>) => void;
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
  const enumChips = (axis: "education" | "demand" | "contract" | "schedule" | "travel" | "environment", values: readonly string[]) =>
    values.map((value) => ({
      value,
      label: valueLabel(value),
      count: facetCount(facets, axis, value),
      testId: `catalog-${axis}-${value}`,
    }));

  const familyChips = flattenFamilies(families).map(({ node, depth }) => ({
    value: node.key,
    label: `${"\u00a0".repeat(depth * 2)}${node.label}`,
    count: facetCount(facets, "family", node.key) ?? node.job_count,
    testId: `catalog-family-${node.key}`,
  }));

  const interestValues = selectedValues(
    Object.keys(facets.interests ?? {}),
    filters.interests,
    filters.interestsExclude
  );

  return (
    <div
      className="space-y-2 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
      data-testid="catalog-filter-rail"
    >
      <Section
        title={t("catalog.filters.skills")}
        active={filters.skills.length + filters.skillsExclude.length + (filters.minLevel ? 1 : 0) > 0}
        count={filters.skills.length + filters.skillsExclude.length}
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
                  className="rounded border border-[var(--as-border)] bg-[var(--as-muted)] px-1.5 py-0.5 text-[10px] text-[var(--as-muted-fg)] disabled:opacity-40"
                  data-testid={`catalog-skill-suggestion-${key}`}
                >
                  {key} · {count}
                </button>
              ))}
          </div>
        ) : null}
      </Section>

      <Section
        title={t("catalog.filters.family")}
        active={filters.family !== ""}
        defaultOpen
      >
        <TriStateChips
          showCounts
          allowExclude={false}
          values={familyChips}
          include={filters.family ? [filters.family] : []}
          exclude={[]}
          onToggle={(value, mode) => onChange({ family: mode === "clear" ? "" : value })}
        />
      </Section>

      <Section
        title={t("catalog.filters.interests")}
        active={filters.interests.length + filters.interestsExclude.length > 0}
        count={filters.interests.length + filters.interestsExclude.length}
      >
        <TriStateChips
          showCounts
          values={interestValues.map((value) => ({
            value,
            label: value,
            count: facetCount(facets, "interests", value),
            testId: `catalog-interest-${value}`,
          }))}
          include={filters.interests}
          exclude={filters.interestsExclude}
          onToggle={(value, mode) => {
            const next = triStateToggle(
              filters.interests,
              filters.interestsExclude,
              value,
              mode
            );
            onChange({ interests: next.include, interestsExclude: next.exclude });
          }}
        />
      </Section>

      <Section
        title={t("catalog.filters.education")}
        active={
          filters.education.length + filters.educationExclude.length + (filters.educationMin ? 1 : 0) >
          0
        }
        count={filters.education.length + filters.educationExclude.length}
      >
        <TriStateChips
          showCounts
          values={enumChips("education", EDUCATION_VALUES)}
          include={filters.education}
          exclude={filters.educationExclude}
          onToggle={(value, mode) =>
            toggle("education", filters.education, filters.educationExclude, value, mode)
          }
        />
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
      </Section>

      <Section
        title={t("catalog.filters.demand")}
        active={filters.demand.length + filters.demandExclude.length > 0}
        count={filters.demand.length + filters.demandExclude.length}
      >
        <TriStateChips
          showCounts
          values={enumChips("demand", DEMAND_VALUES)}
          include={filters.demand}
          exclude={filters.demandExclude}
          onToggle={(value, mode) =>
            toggle("demand", filters.demand, filters.demandExclude, value, mode)
          }
        />
      </Section>

      <Section
        title={t("catalog.filters.salary")}
        active={filters.salaryMin !== "" || filters.salaryMax !== ""}
        count={(filters.salaryMin ? 1 : 0) + (filters.salaryMax ? 1 : 0)}
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
      </Section>

      <Section
        title={t("catalog.filters.contract")}
        active={filters.contract.length + filters.contractExclude.length > 0}
        count={filters.contract.length + filters.contractExclude.length}
      >
        <TriStateChips
          showCounts
          values={enumChips("contract", CONTRACT_VALUES)}
          include={filters.contract}
          exclude={filters.contractExclude}
          onToggle={(value, mode) =>
            toggle("contract", filters.contract, filters.contractExclude, value, mode)
          }
        />
      </Section>

      <Section
        title={t("catalog.filters.schedule")}
        active={filters.schedule.length + filters.scheduleExclude.length > 0}
        count={filters.schedule.length + filters.scheduleExclude.length}
      >
        <TriStateChips
          showCounts
          values={enumChips("schedule", SCHEDULE_VALUES)}
          include={filters.schedule}
          exclude={filters.scheduleExclude}
          onToggle={(value, mode) =>
            toggle("schedule", filters.schedule, filters.scheduleExclude, value, mode)
          }
        />
      </Section>

      <Section
        title={t("catalog.filters.travel")}
        active={filters.travel.length + filters.travelExclude.length > 0}
        count={filters.travel.length + filters.travelExclude.length}
      >
        <TriStateChips
          showCounts
          values={enumChips("travel", TRAVEL_VALUES)}
          include={filters.travel}
          exclude={filters.travelExclude}
          onToggle={(value, mode) =>
            toggle("travel", filters.travel, filters.travelExclude, value, mode)
          }
        />
      </Section>

      <Section
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
      </Section>

      <Section
        title={t("catalog.filters.environment")}
        active={filters.environment.length + filters.environmentExclude.length > 0}
        count={filters.environment.length + filters.environmentExclude.length}
      >
        <TriStateChips
          showCounts
          values={enumChips("environment", ENVIRONMENT_VALUES)}
          include={filters.environment}
          exclude={filters.environmentExclude}
          onToggle={(value, mode) =>
            toggle("environment", filters.environment, filters.environmentExclude, value, mode)
          }
        />
      </Section>

      <Section
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
      </Section>
    </div>
  );
}
