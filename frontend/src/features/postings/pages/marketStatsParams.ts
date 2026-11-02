import type {
  MarketDimension,
  MarketStatsQuery,
  MarketWindow,
  StatsStatusBasis,
  TimeseriesSplit,
} from "@/api/stats";

/** The `/postings/stats` URL vocabulary (ui-conventions §2h): the URL is
 * the state — one pure parse helper, unknown values fall back to the
 * defaults, writes carry `replace: true` and one canonicalization effect
 * cleans stale params. Comparison state rides the same law (plan 171
 * H9): `compare` prefers `previous` (today's default-on ghost), and a
 * `custom` choice with missing or dangling dates drops to it. */
export const MARKET_WINDOWS = ["24h", "7d", "30d", "90d", "all"] as const;

export const MARKET_DIMENSIONS = [
  "seniority",
  "work_mode",
  "employment",
  "contract",
  "education",
  "source",
  "location",
  "org",
  "family",
] as const;

export const TIMESERIES_SPLITS = [
  "status",
  "source",
  "work_mode",
  "seniority",
  "employment",
] as const;

export const BASIS_VALUES = ["open", "all"] as const;

export const COMPARE_MODES = ["off", "previous", "custom"] as const;

export type CompareMode = (typeof COMPARE_MODES)[number];

export type ViewWindow = MarketWindow | "custom";

export interface MarketStatsView {
  /** Preset window, or `custom` with an explicit `from`/`to` pair. */
  window: ViewWindow;
  /** ISO date (yyyy-mm-dd) — only honored in the `custom` window. */
  from: string;
  /** ISO date (yyyy-mm-dd), inclusive of that whole day when written. */
  to: string;
  basis: StatsStatusBasis;
  split: TimeseriesSplit | "";
  dimension: MarketDimension;
  /** The comparison overlay: `previous` keeps the equal-length ghost
   * equivalent, `custom` overlays the `compare_from`/`compare_to` B
   * window, `off` turns the comparison off. */
  compare: CompareMode;
  /** ISO dates — the B window; only written/handled when
   * `compare=custom`. */
  compare_from: string;
  compare_to: string;
}

export const DEFAULT_VIEW: MarketStatsView = {
  window: "30d",
  from: "",
  to: "",
  basis: "all",
  split: "",
  dimension: "source",
  compare: "previous",
  compare_from: "",
  compare_to: "",
};

const WINDOWS: ReadonlyArray<string> = [...MARKET_WINDOWS, "custom"];
const DIMENSIONS: ReadonlyArray<string> = MARKET_DIMENSIONS;
const SPLITS: ReadonlyArray<string> = TIMESERIES_SPLITS;
const BASES: ReadonlyArray<string> = BASIS_VALUES;
const COMPARES: ReadonlyArray<string> = COMPARE_MODES;

/** An ISO calendar date (yyyy-mm-dd) whose fields name a real day. */
function isIsoDate(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const [, year, month, day] = match;
  const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  return (
    date.getUTCFullYear() === Number(year) &&
    date.getUTCMonth() === Number(month) - 1 &&
    date.getUTCDate() === Number(day)
  );
}

export function parseView(params: URLSearchParams): MarketStatsView {
  const window = WINDOWS.includes(params.get("window") ?? "")
    ? (params.get("window") as ViewWindow)
    : DEFAULT_VIEW.window;
  const from = (params.get("from") ?? "").slice(0, 10);
  const to = (params.get("to") ?? "").slice(0, 10);
  const customWithoutRange = window === "custom" && (!from || !to);
  const splitParam = (params.get("split") ?? "")
    .trim()
    .toLowerCase();
  const dimensionParam = (params.get("dimension") ?? "")
    .trim()
    .toLowerCase();
  const basisParam = (params.get("basis") ?? "")
    .trim()
    .toLowerCase();
  const compareParam = (params.get("compare") ?? "")
    .trim()
    .toLowerCase();
  const compareFrom = (params.get("compare_from") ?? "").slice(0, 10);
  const compareTo = (params.get("compare_to") ?? "").slice(0, 10);
  // A custom comparison with dangling or impossible dates drops the
  // compare state to `previous`, never half-alive; both dates pending
  // stays `custom` (the pair reveals, the page hints, nothing fetches).
  let compare: CompareMode = (COMPARES.includes(compareParam)
    ? compareParam
    : DEFAULT_VIEW.compare) as CompareMode;
  if (
    compare === "custom" &&
    (compareFrom !== "" || compareTo !== "") &&
    (!isIsoDate(compareFrom) || (compareTo !== "" && !isIsoDate(compareTo)))
  ) {
    compare = "previous";
  }
  return {
    window: customWithoutRange ? DEFAULT_VIEW.window : window,
    from,
    to,
    basis: (BASES.includes(basisParam) ? basisParam : DEFAULT_VIEW.basis) as StatsStatusBasis,
    split: (SPLITS.includes(splitParam) ? splitParam : "") as TimeseriesSplit | "",
    dimension:
      (DIMENSIONS.includes(dimensionParam)
        ? dimensionParam
        : DEFAULT_VIEW.dimension) as MarketDimension,
    compare,
    compare_from: compare === "custom" ? compareFrom : "",
    compare_to: compare === "custom" ? compareTo : "",
  };
}

export function isDefault(view: MarketStatsView): boolean {
  return view.window === DEFAULT_VIEW.window && view.basis === "all" && !view.split;
}

/** The API query one view resolves to: a custom range is written
 * end-exclusive (`to` = the day after, 00:00 local) like the audit
 * `RangeFilter` — `from`/`to` win over the preset server-side. */
export function rangeQuery(view: MarketStatsView): MarketStatsQuery {
  if (view.window === "custom") {
    const [year, month, day] = view.to.split("-").map(Number);
    return {
      from: `${view.from}T00:00:00`,
      to: `${new Date(Date.UTC(year, month - 1, day + 1)).toISOString().slice(0, 10)}T00:00:00`,
    };
  }
  return { window: view.window };
}

export function toSearchParams(view: MarketStatsView): URLSearchParams {
  const params = new URLSearchParams();
  if (view.window !== DEFAULT_VIEW.window) params.set("window", view.window);
  if (view.window === "custom") {
    params.set("from", view.from);
    params.set("to", view.to);
  }
  if (view.basis !== "all") params.set("basis", view.basis);
  if (view.split) params.set("split", view.split);
  if (view.dimension !== DEFAULT_VIEW.dimension)
    params.set("dimension", view.dimension);
  if (view.compare !== DEFAULT_VIEW.compare) params.set("compare", view.compare);
  if (view.compare === "custom") {
    if (view.compare_from) params.set("compare_from", view.compare_from);
    if (view.compare_to) params.set("compare_to", view.compare_to);
  }
  return params;
}

/** One preset window's span in days. */
const PRESET_SPANS: Record<Exclude<MarketWindow, "all">, number> = {
  "24h": 1,
  "7d": 7,
  "30d": 30,
  "90d": 90,
};

/** A window's span in whole days; `null` = undefined (`all` has no edge,
 * or a custom range missing an end). */
export function spanDays(view: MarketStatsView): number | null {
  if (view.window === "custom") {
    if (!isIsoDate(view.from) || !isIsoDate(view.to)) return null;
    return Math.max(
      1,
      Math.round(
        (Date.parse(`${view.to}T00:00:00Z`) - Date.parse(`${view.from}T00:00:00Z`)) / 86_400_000,
      ) + 1,
    );
  }
  return PRESET_SPANS[view.window as Exclude<MarketWindow, "all">] ?? null;
}

/** ISO-date calendar arithmetic (UTC). */
export function addIsoDays(iso: string, days: number): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10);
}

export interface CompareRange {
  from: string;
  to: string;
}

/** The B window one view's comparison resolves to, when both ends are
 * known: a set `compare_to` wins; otherwise B ends `compare_from` +
 * A's span — except in `window=all`, where A's span is undefined and
 * the auto-prefill is disabled until the user picks both dates (null
 * here; the page hints). Both `from`/`to` are inclusive days. */
export function compareRange(view: MarketStatsView): CompareRange | null {
  if (view.compare !== "custom" || !isIsoDate(view.compare_from)) return null;
  if (isIsoDate(view.compare_to)) {
    return { from: view.compare_from, to: view.compare_to };
  }
  const span = spanDays(view);
  if (!span) return null;
  return { from: view.compare_from, to: addIsoDays(view.compare_from, span - 1) };
}
