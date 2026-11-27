/**
 * The findings filter rail (plan 175 S2, C1.1): the shared filter module
 * (`FilterRail` + `FilterSection` + `FacetChip`) with the findings
 * vocabulary — state + dedupe/applied toggles, score/coverage bounds, org
 * text, source/seniority facet chips with self-excluding counts, remote and
 * posted-within. Own small filter set; the /postings engine's axes don't
 * apply here. Sections carry no count: a facet count is never put in the
 * section's active slot, and the active dot already marks the state.
 */

import { useTranslation } from "react-i18next";
import {
  FacetChip,
  FilterRail,
  FilterSection,
} from "@neuronection/assistant-ui/filters";

import type { FindingFeedFacets } from "@/api/autopilot";
import type { ContainerBand } from "@/hooks/useContainerBand";
import {
  FINDINGS_POSTED_WINDOWS,
  FINDINGS_SENIORITIES,
  countActiveFindingsFilters,
  type FindingsFilters,
} from "@/features/growth/findingsFilterState";
import type { CountsState, FacetValue } from "@/lib/filterFacets";
import {
  facetLabels,
  facetOptions,
  railLabels,
  railLayout,
  singleValue,
} from "@/lib/filterFacets";

interface FindingsRailProps {
  filters: FindingsFilters;
  facets: FindingFeedFacets | null;
  sources: { key: string; label: string }[];
  onChange: (next: FindingsFilters) => void;
  onClear: () => void;
  band?: ContainerBand;
  /** Whether `facets` is still the last successful feed response. */
  counts?: CountsState;
}

/** One single-valued findings axis: one option set, one value or none. */
function SingleFacet({
  id,
  label,
  values,
  value,
  counts,
  onChange,
  labels,
}: {
  id: string;
  label: string;
  values: FacetValue[];
  value: string | null;
  counts: CountsState;
  onChange: (value: string | null) => void;
  labels: ReturnType<typeof facetLabels>;
}) {
  return (
    <FacetChip
      facet={{
        id,
        label,
        kind: "single",
        countsState: counts,
        options: facetOptions(values, { include: value ? [value] : [] }),
      }}
      value={singleValue(value)}
      variant="inline"
      showActivePills={false}
      labels={labels}
      onToggleOption={(option, action) => {
        if (option === null) return;
        onChange(action === "clear" ? null : option);
      }}
      testId={`${id}-facet`}
      optionTestId={(option) => `${id}-${option ?? "not-recorded"}`}
    />
  );
}

export function FindingsRail({
  filters,
  facets,
  sources,
  onChange,
  onClear,
  band,
  counts = "ready",
}: FindingsRailProps) {
  const { t } = useTranslation();
  const active = countActiveFindingsFilters(filters);
  const labels = facetLabels(t);

  return (
    <FilterRail
      layout={railLayout(band)}
      title={t("autopilot.workspace.filtersTitle")}
      labels={railLabels(t)}
      activeCount={active === 0 ? undefined : active}
      onClear={active === 0 ? undefined : onClear}
      className="ca-stats-rail"
      data-testid="autopilot-filters"
    >
      <FilterSection
        title={t("autopilot.workspace.stateSection")}
        active={filters.state !== "open" || !filters.latest || filters.hideApplied}
      >
        <SingleFacet
          id="state"
          label={t("autopilot.workspace.stateSection")}
          values={[
            { value: "open", label: t("autopilot.workspace.stateOpen") },
            { value: "dismissed", label: t("autopilot.workspace.stateDismissed") },
            { value: "all", label: t("autopilot.workspace.stateAll") },
          ]}
          value={filters.state}
          onChange={(value) =>
            onChange({
              ...filters,
              state: (value ?? "open") as FindingsFilters["state"],
            })
          }
          counts={counts}
          labels={labels}
        />
        <label className="flex items-center justify-between text-xs text-[var(--as-muted-fg)]">
          {t("autopilot.workspace.latestOnly")}
          <input
            type="checkbox"
            checked={filters.latest}
            onChange={(e) => onChange({ ...filters, latest: e.target.checked })}
            data-testid="findings-latest-toggle"
          />
        </label>
        <label className="flex items-center justify-between text-xs text-[var(--as-muted-fg)]">
          {t("autopilot.workspace.hideApplied")}
          <input
            type="checkbox"
            checked={filters.hideApplied}
            onChange={(e) => onChange({ ...filters, hideApplied: e.target.checked })}
            data-testid="findings-hide-applied-toggle"
          />
        </label>
      </FilterSection>

      <FilterSection
        title={t("autopilot.workspace.scoreSection")}
        active={filters.minScore !== null || filters.coverageMin !== null}
      >
        <div className="flex items-center gap-2">
          <label className="text-xs text-[var(--as-muted-fg)]" htmlFor="findings-min-score">
            {t("autopilot.workspace.minScore")}
          </label>
          <input
            id="findings-min-score"
            type="number"
            min={0}
            max={10}
            step={0.5}
            className="w-16 rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-sm text-[var(--as-fg)]"
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
          <label className="text-xs text-[var(--as-muted-fg)]" htmlFor="findings-coverage-min">
            {t("autopilot.workspace.coverageMin")}
          </label>
          <input
            id="findings-coverage-min"
            type="number"
            min={0}
            max={20}
            className="w-16 rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-sm text-[var(--as-fg)]"
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
      </FilterSection>

      <FilterSection title={t("autopilot.workspace.orgSection")} active={!!filters.org.trim()}>
        <input
          className="w-full rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-sm text-[var(--as-fg)]"
          placeholder={t("autopilot.workspace.orgPlaceholder")}
          value={filters.org}
          onChange={(e) => onChange({ ...filters, org: e.target.value })}
          data-testid="findings-org-input"
        />
      </FilterSection>

      <FilterSection
        title={t("autopilot.workspace.sourceSection")}
        active={!!filters.source}
      >
        <SingleFacet
          id="source"
          label={t("autopilot.workspace.sourceSection")}
          values={sources.map((source) => ({
            value: source.key,
            label: source.label,
            count: facets?.source?.[source.key],
          }))}
          value={filters.source}
          onChange={(value) => onChange({ ...filters, source: value })}
          counts={counts}
          labels={labels}
        />
        {sources.length === 0 ? (
          <p className="text-xs text-[var(--as-muted-fg)]">{t("autopilot.workspace.noSources")}</p>
        ) : null}
      </FilterSection>

      <FilterSection
        title={t("autopilot.workspace.senioritySection")}
        active={!!filters.seniority}
      >
        <SingleFacet
          id="seniority"
          label={t("autopilot.workspace.senioritySection")}
          values={FINDINGS_SENIORITIES.map((value) => ({
            value,
            label: t(`autopilot.seniority.${value}`, { defaultValue: value }),
            count: facets?.seniority?.[value],
          }))}
          value={filters.seniority}
          onChange={(value) => onChange({ ...filters, seniority: value })}
          counts={counts}
          labels={labels}
        />
      </FilterSection>

      <FilterSection title={t("autopilot.workspace.remoteSection")} active={filters.remote}>
        <label className="flex items-center justify-between text-xs text-[var(--as-muted-fg)]">
          {t("autopilot.workspace.remoteOnly")}
          <input
            type="checkbox"
            checked={filters.remote}
            onChange={(e) => onChange({ ...filters, remote: e.target.checked })}
            data-testid="findings-remote-toggle"
          />
        </label>
      </FilterSection>

      <FilterSection title={t("autopilot.workspace.postedSection")} active={!!filters.postedWithin}>
        <SingleFacet
          id="posted"
          label={t("autopilot.workspace.postedSection")}
          values={FINDINGS_POSTED_WINDOWS.map((window) => ({
            value: window,
            label: window,
          }))}
          value={filters.postedWithin || null}
          onChange={(value) => onChange({ ...filters, postedWithin: value ?? "" })}
          counts={counts}
          labels={labels}
        />
      </FilterSection>
    </FilterRail>
  );
}
