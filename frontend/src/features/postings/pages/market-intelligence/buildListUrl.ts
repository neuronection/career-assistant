import type { MarketSegments, MarketStatsView, ViewWindow } from "../marketStatsParams";

const PRESET_ORDER = ["24h", "7d", "30d", "90d"] as const;

/** The nearest preset for a window — `all` and a missing custom range
 * have no list equivalent, a custom range snaps to the closest preset
 * (the shell shows the honest hint). */
export function drillWindow(view: MarketStatsView): (typeof PRESET_ORDER)[number] | null {
  if (view.window === "all") return null;
  if (view.window !== "custom") return view.window;
  const span = customSpanDays(view);
  if (span === null) return null;
  if (span <= 1) return "24h";
  if (span <= 7) return "7d";
  if (span <= 30) return "30d";
  if (span <= 90) return "90d";
  return null;
}

function customSpanDays(view: MarketStatsView): number | null {
  if (view.window !== "custom") return null;
  if (!view.from || !view.to) return null;
  const from = Date.parse(`${view.from}T00:00:00Z`);
  const to = Date.parse(`${view.to}T00:00:00Z`);
  if (Number.isNaN(from) || Number.isNaN(to) || to < from) return null;
  return Math.round((to - from) / 86_400_000) + 1;
}

export function isExactDrillWindow(view: MarketStatsView): boolean {
  if (view.window !== "custom") return true;
  return drillWindow(view) !== null && customSpanDays(view) === presetDays(drillWindow(view));
}

function presetDays(window: ViewWindow | null): number | null {
  if (window === "24h") return 1;
  if (window === "7d") return 7;
  if (window === "30d") return 30;
  if (window === "90d") return 90;
  return null;
}

function appendSegments(params: URLSearchParams, segments: MarketSegments): void {
  if (segments.source.length) params.set("source", segments.source.join(","));
  for (const org of segments.org) params.append("org", org);
  if (segments.mapped_family.length)
    params.set("mapped_family", segments.mapped_family.join(","));
  if (segments.seniority.length) params.set("seniority", segments.seniority.join(","));
  if (segments.remote_policy.length)
    params.set("remote_policy", segments.remote_policy.join(","));
  if (segments.employment_type.length)
    params.set("employment_type", segments.employment_type.join(","));
  if (segments.contract.length) params.set("contract", segments.contract.join(","));
  if (segments.education_min) params.set("education_min", segments.education_min);
  if (segments.city) params.set("city", segments.city);
  if (segments.country) params.set("country", segments.country);
  if (segments.skills) params.set("skills", segments.skills);
  if (segments.skill_mode === "any") params.set("skill_mode", "any");
  if (segments.salary_min) params.set("salary_min", segments.salary_min);
  if (segments.q) params.set("q", segments.q);
  if (segments.hidden_include) params.set("hidden_include", "true");
}

/** The `/postings` deep link for a card row: the page window (as the
 * nearest preset `posted_within`), the status basis and every active
 * segment. The list is the one population the card counted. */
export function buildListUrl(view: MarketStatsView): string {
  const params = new URLSearchParams();
  const window = drillWindow(view);
  if (window) params.set("posted_within", window);
  if (view.basis === "all") params.set("basis", "all");
  appendSegments(params, view.segments);
  const query = params.toString();
  return query ? `/postings?${query}` : "/postings";
}

/** The all-time open population a `open_total` tile counts: no window,
 * the list's default open basis, and the active segments. */
export function buildOpenTotalUrl(view: MarketStatsView): string {
  const params = new URLSearchParams();
  appendSegments(params, view.segments);
  const query = params.toString();
  return query ? `/postings?${query}` : "/postings";
}
