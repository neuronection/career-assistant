/**
 * Career's mapping onto the shared filter module (plan C1.1): the URL state
 * stays career-shaped (`include`/`exclude` string arrays per axis) and every
 * rail renders the family `FacetChip`/`FilterSection`/`FilterRail` from
 * `@neuronection/assistant-ui/filters`. Nothing here renders — it is the
 * pure translation between the two shapes, so the three career URL
 * encodings and their allowlists stay untouched.
 */

import type {
  FacetChipLabels,
  FilterFacet,
  FilterOption,
  FilterRailLabels,
  FilterRailLayout,
  FilterValue,
} from "@neuronection/assistant-ui/filters";

import type { ContainerBand } from "@/hooks/useContainerBand";

/** One facet value as career pages know it: label + the count it was given.
 * `null` is the shared module's “not recorded” bucket, not a sentinel string. */
export interface FacetValue {
  value: string | null;
  label: string;
  count?: number;
  /** The host truncated the bucket, so the shared chip renders `≥N`. */
  countAtLeast?: boolean;
  hint?: string;
}

export type Translate = (key: string, options?: Record<string, unknown>) => string;

export type TriStateMode = "include" | "exclude" | "clear";

/** The facet count trust state the shared chip understands. */
export type CountsState = NonNullable<FilterFacet["countsState"]>;

/**
 * What a facet's counts are worth right now. The shared chip withholds every
 * number (and its accessible-name suffix) unless this is `ready`, and marks
 * itself `aria-busy` while loading. Pass `failed` when the last request
 * rejected: the numbers on screen are stale, so none may be rendered.
 */
export function countsState({
  loading = false,
  failed = false,
}: {
  loading?: boolean;
  failed?: boolean;
} = {}): CountsState {
  if (failed) return "error";
  return loading ? "loading" : "ready";
}

/**
 * The tri-state cycle for one value: off → include → exclude → off.
 * Include and exclude are mutually exclusive per value (every mode drops the
 * value from the other list).
 */
export function triStateToggle(
  include: readonly string[],
  exclude: readonly string[],
  value: string,
  mode: TriStateMode
): { include: string[]; exclude: string[] } {
  if (mode === "clear") {
    return {
      include: include.filter((v) => v !== value),
      exclude: exclude.filter((v) => v !== value),
    };
  }
  if (mode === "exclude") {
    return {
      include: include.filter((v) => v !== value),
      exclude: [...exclude.filter((v) => v !== value), value],
    };
  }
  return {
    include: [...include.filter((v) => v !== value), value],
    exclude: exclude.filter((v) => v !== value),
  };
}

/**
 * Career's include/exclude pair as the shared multi value.
 */
export function multiValue(
  include: readonly (string | null)[],
  exclude: readonly (string | null)[] = []
): FilterValue {
  return { kind: "multi", include: [...include], exclude: [...exclude] };
}

/** Career's single-valued axis (one value or none) as the shared single value. */
export function singleValue(value: string | null): FilterValue {
  return { kind: "single", value };
}

/**
 * Resolve facet options for the shared chip.
 *
 * A value that is applied but missing from the source list is kept — with no
 * count — so a URL-borne or stale selection stays visible and removable
 * (plan §3.2/D15) instead of narrowing the list invisibly. Counts are copied
 * only when the host actually has one: no count is ever invented, and `0` from
 * a facet is passed through as a real zero.
 */
export function facetOptions(
  values: FacetValue[],
  selected: {
    include?: (string | null)[];
    exclude?: (string | null)[];
  } = {}
): FilterOption[] {
  const options: FilterOption[] = values.map((entry) => ({
    value: entry.value,
    label: entry.label,
    ...(entry.count === undefined ? {} : { count: entry.count }),
    ...(entry.countAtLeast ? { countAtLeast: true } : {}),
    ...(entry.hint === undefined ? {} : { hint: entry.hint }),
  }));
  const known = new Set(options.map((option) => option.value));
  for (const value of [...(selected.include ?? []), ...(selected.exclude ?? [])]) {
    if (value === null || known.has(value)) continue;
    known.add(value);
    options.push({ value, label: value });
  }
  return options;
}

/**
 * The filter module owns no strings: career passes its own. `excluded`,
 * `noneMatch` and `notRecorded` are the AT-only suffixes/names the shared
 * chip and section need; the menu words name the tri-state row actions.
 */
export function facetLabels(t: Translate): FacetChipLabels {
  return {
    excluded: t("filters.excluded"),
    noneMatch: t("filters.noneMatch"),
    notRecorded: t("filters.notRecorded"),
    remove: (label) => t("filters.removeValue", { value: label }),
    include: t("filters.include"),
    exclude: t("filters.exclude"),
    clear: t("filters.clickToClear"),
    optionMenu: (label) => t("filters.optionMenu", { value: label }),
  };
}

/**
 * The page-container band → shared rail layout. `wide` keeps the vertical
 * rail; every narrower band uses the compact toolbar + `PanelModal` sheet.
 * Measured on the page container (never the viewport): the chat dock narrows
 * the column without moving the viewport.
 */
export function railLayout(band?: ContainerBand): FilterRailLayout {
  return (band ?? "wide") === "wide" ? "rail" : "compact";
}

/** The shared rail's own strings, in career's locale. */
export function railLabels(t: Translate): FilterRailLabels {
  return {
    filters: t("filters.title"),
    clearAll: t("filters.clearAll"),
    close: t("filters.close"),
    done: t("filters.done"),
  };
}
