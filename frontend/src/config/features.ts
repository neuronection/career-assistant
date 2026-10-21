import registry from "./features.json";

/**
 * Support level of one user-facing surface.
 *
 * - `on` — shipped and fully supported.
 * - `beta` — reachable, with a visible beta chip and one expectation line.
 * - `hidden` — kept routable for deep links but absent from navigation and
 *   the demo tour.
 */
export type FeatureState = "on" | "beta" | "hidden";

export interface FeatureEntry {
  /** Route prefix this feature is reached at (the nav + tour key). */
  key: string;
  state: FeatureState;
  /** ISO date the current state was decided. */
  since: string;
  /** Tracked documentation page that describes the surface. */
  docs: string;
}

/**
 * The single feature-state table: navigation visibility, the beta banner,
 * the demo tour and the docs-claims test all read this file, so they
 * cannot disagree. A route absent from the table is `on`.
 */
export const FEATURES: FeatureEntry[] = registry.features as FeatureEntry[];

/**
 * The registry entry covering a pathname, by longest matching route prefix.
 * `/postings/search` resolves to the `/postings` entry.
 */
export function featureFor(pathname: string): FeatureEntry | null {
  const matches = FEATURES.filter(
    (feature) =>
      pathname === feature.key || pathname.startsWith(`${feature.key}/`)
  ).sort((a, b) => b.key.length - a.key.length);
  return matches[0] ?? null;
}

/** Whether a pathname may be shown in navigation, the tour and deep links. */
export function isVisible(pathname: string): boolean {
  return featureFor(pathname)?.state !== "hidden";
}

/** The beta surfaces, in registry order. */
export function betaFeatures(): FeatureEntry[] {
  return FEATURES.filter((feature) => feature.state === "beta");
}
