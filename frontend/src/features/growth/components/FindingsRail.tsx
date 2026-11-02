/**
 * The findings filter rail (plan 175 S2): the shared filterBits
 * primitives with the findings vocabulary — state + dedupe/applied
 * toggles, score/coverage bounds, org text, source/seniority facet
 * chips with self-excluding counts, remote and posted-within. Own small
 * filter set; the /postings engine's axes don't apply here.
 */

import { useTranslation } from "react-i18next";

import type { FindingFeedFacets } from "@/api/autopilot";
import { Section, TriStateChips } from "@/components/filters/filterBits";
import {
  FINDINGS_POSTED_WINDOWS,
  FINDINGS_SENIORITIES,
  countActiveFindingsFilters,
  type FindingsFilters,
} from "@/features/growth/findingsFilterState";

interface FindingsRailProps {
  filters: FindingsFilters;
  facets: FindingFeedFacets | null;
  sources: { key: string; label: string }[];
  onChange: (next: FindingsFilters) => void;
  onClear: () => void;
}

export function FindingsRail({
  filters,
  facets,
  sources,
  onChange,
  onClear,
}: FindingsRailProps) {
  const { t } = useTranslation();
  const active = countActiveFindingsFilters(filters);

  return (
    <div
      className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3 space-y-3"
      data-testid="findings-rail"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-semibold text-slate-700">
          {t("autopilot.workspace.filtersTitle")}
          {active > 0 ? (
            <span className="ml-2 text-xs text-primary-600" data-testid="findings-filter-count">
              {t("filters.activeCount", { count: active })}
            </span>
          ) : null}
        </div>
        {active > 0 ? (
          <button
            type="button"
            className="text-xs text-slate-400 hover:text-slate-600"
            onClick={onClear}
            data-testid="findings-filter-clear"
          >
            {t("filters.clearAll")}
          </button>
        ) : null}
      </div>

      <Section title={t("autopilot.workspace.stateSection")} active={filters.state !== "open" || !filters.latest || filters.hideApplied}>
        <TriStateChips
          values={[
            { value: "open", label: t("autopilot.workspace.stateOpen") },
            { value: "dismissed", label: t("autopilot.workspace.stateDismissed") },
            { value: "all", label: t("autopilot.workspace.stateAll") },
          ]}
          include={[filters.state]}
          exclude={[]}
          allowExclude={false}
          onToggle={(value) =>
            onChange({ ...filters, state: value as FindingsFilters["state"] })
          }
        />
        <label className="flex items-center justify-between text-xs text-slate-600">
          {t("autopilot.workspace.latestOnly")}
          <input
            type="checkbox"
            checked={filters.latest}
            onChange={(e) => onChange({ ...filters, latest: e.target.checked })}
            data-testid="findings-latest-toggle"
          />
        </label>
        <label className="flex items-center justify-between text-xs text-slate-600">
          {t("autopilot.workspace.hideApplied")}
          <input
            type="checkbox"
            checked={filters.hideApplied}
            onChange={(e) => onChange({ ...filters, hideApplied: e.target.checked })}
            data-testid="findings-hide-applied-toggle"
          />
        </label>
      </Section>

      <Section
        title={t("autopilot.workspace.scoreSection")}
        active={filters.minScore !== null || filters.coverageMin !== null}
      >
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-500" htmlFor="findings-min-score">
            {t("autopilot.workspace.minScore")}
          </label>
          <input
            id="findings-min-score"
            type="number"
            min={0}
            max={10}
            step={0.5}
            className="w-16 text-sm border border-slate-200 rounded px-2 py-1"
            value={filters.minScore ?? ""}
            onChange={(e) =>
              onChange({
                ...filters,
                minScore: e.target.value ? Number(e.target.value) : null,
              })
            }
            data-testid="findings-min-score"
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-500" htmlFor="findings-coverage-min">
            {t("autopilot.workspace.coverageMin")}
          </label>
          <input
            id="findings-coverage-min"
            type="number"
            min={0}
            max={20}
            className="w-16 text-sm border border-slate-200 rounded px-2 py-1"
            value={filters.coverageMin ?? ""}
            onChange={(e) =>
              onChange({
                ...filters,
                coverageMin: e.target.value ? Number(e.target.value) : null,
              })
            }
            data-testid="findings-coverage-min"
          />
        </div>
      </Section>

      <Section title={t("autopilot.workspace.orgSection")} active={!!filters.org.trim()}>
        <input
          className="w-full text-sm border border-slate-200 rounded-lg px-2 py-1"
          placeholder={t("autopilot.workspace.orgPlaceholder")}
          value={filters.org}
          onChange={(e) => onChange({ ...filters, org: e.target.value })}
          data-testid="findings-org-input"
        />
      </Section>

      <Section
        title={t("autopilot.workspace.sourceSection")}
        active={!!filters.source}
        count={filters.source ? facets?.source?.[filters.source] : undefined}
      >
        <TriStateChips
          values={sources.map((source) => ({
            value: source.key,
            label: source.label,
            count: facets?.source?.[source.key] ?? 0,
            testId: `source-${source.key}`,
          }))}
          include={filters.source ? [filters.source] : []}
          exclude={[]}
          allowExclude={false}
          showCounts
          onToggle={(value) =>
            onChange({ ...filters, source: filters.source === value ? null : value })
          }
        />
        {sources.length === 0 ? (
          <p className="text-xs text-slate-400">{t("autopilot.workspace.noSources")}</p>
        ) : null}
      </Section>

      <Section
        title={t("autopilot.workspace.senioritySection")}
        active={!!filters.seniority}
        count={filters.seniority ? facets?.seniority?.[filters.seniority] : undefined}
      >
        <TriStateChips
          values={FINDINGS_SENIORITIES.map((value) => ({
            value,
            label: t(`autopilot.seniority.${value}`, { defaultValue: value }),
            count: facets?.seniority?.[value] ?? 0,
            testId: `seniority-${value}`,
          }))}
          include={filters.seniority ? [filters.seniority] : []}
          exclude={[]}
          allowExclude={false}
          showCounts
          onToggle={(value) =>
            onChange({ ...filters, seniority: filters.seniority === value ? null : value })
          }
        />
      </Section>

      <Section title={t("autopilot.workspace.remoteSection")} active={filters.remote}>
        <label className="flex items-center justify-between text-xs text-slate-600">
          {t("autopilot.workspace.remoteOnly")}
          <input
            type="checkbox"
            checked={filters.remote}
            onChange={(e) => onChange({ ...filters, remote: e.target.checked })}
            data-testid="findings-remote-toggle"
          />
        </label>
      </Section>

      <Section title={t("autopilot.workspace.postedSection")} active={!!filters.postedWithin}>
        <div className="flex flex-wrap gap-1.5">
          {FINDINGS_POSTED_WINDOWS.map((window) => (
            <button
              key={window}
              type="button"
              aria-pressed={filters.postedWithin === window}
              className={`text-xs px-2.5 py-1 rounded-full border ${
                filters.postedWithin === window
                  ? "border-primary-300 bg-primary-50 text-primary-700 font-medium"
                  : "border-slate-200 text-slate-600 hover:bg-slate-50"
              }`}
              onClick={() =>
                onChange({
                  ...filters,
                  postedWithin: filters.postedWithin === window ? "" : window,
                })
              }
            >
              {window}
            </button>
          ))}
        </div>
      </Section>
    </div>
  );
}
