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
 * cleans stale params. */
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
}

export const DEFAULT_VIEW: MarketStatsView = {
  window: "30d",
  from: "",
  to: "",
  basis: "all",
  split: "",
  dimension: "source",
};

const WINDOWS: ReadonlyArray<string> = [...MARKET_WINDOWS, "custom"];
const DIMENSIONS: ReadonlyArray<string> = MARKET_DIMENSIONS;
const SPLITS: ReadonlyArray<string> = TIMESERIES_SPLITS;
const BASES: ReadonlyArray<string> = BASIS_VALUES;

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
  return params;
}
