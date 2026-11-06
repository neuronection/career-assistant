import { useEffect, useState } from "react";

import { fetchPostingStatsDashboard, type MarketDashboard, type PostingStatsTimeseries } from "@/api/stats";
import {
  addIsoDays,
  compareRange,
  dashboardParams,
  type CompareRange,
  type MarketStatsView,
} from "../../marketStatsParams";
import type { CompareOverlay } from "../cards";

export interface TabProps {
  data: MarketDashboard;
  view: MarketStatsView;
  loading: boolean;
  compact: boolean;
  refresh: () => void;
  onPatch: (update: Partial<MarketStatsView>) => void;
  onDrill: (params: string) => void;
  onDrillOpen: () => void;
}

/** The B window one custom comparison reads: the dashboard's own query
 * (so B carries the same compiled filter truth as A) with the range
 * swapped and only the timeseries card requested. */
function compareParams(
  view: MarketStatsView,
  range: CompareRange,
  bucket: PostingStatsTimeseries["bucket"] | undefined,
): Record<string, string | string[] | number | boolean> {
  const params = dashboardParams(view);
  delete params.window;
  delete params.split;
  delete params.dimension;
  params.from = `${range.from}T00:00:00`;
  params.to = `${addIsoDays(range.to, 1)}T00:00:00`;
  params.cards = "timeseries";
  if (bucket) params.bucket = bucket;
  return params;
}

/** The custom-B overlay: a second timeseries read when compare=custom is
 * active without a split (split and comparison answer one question at a
 * time). Bucket alignment is by position — B is a different range. The
 * request key is a string, so a state update from the response cannot
 * retrigger the effect (the range object is rebuilt each render). */
export function useCompareSeries(
  view: MarketStatsView,
  series: PostingStatsTimeseries | null,
): { overlay: CompareOverlay | null; error: boolean } {
  const [compareSeries, setCompareSeries] = useState<PostingStatsTimeseries | null>(null);
  const [error, setError] = useState(false);
  const range = compareRange(view);
  const params = range ? compareParams(view, range, series?.bucket) : null;
  const key = params ? JSON.stringify(params) : "";

  useEffect(() => {
    if (!key || view.compare !== "custom" || view.split || !series) {
      setCompareSeries(null);
      setError(false);
      return;
    }
    let alive = true;
    const controller = new AbortController();
    fetchPostingStatsDashboard(
      JSON.parse(key) as Record<string, string | string[] | number | boolean>,
      controller.signal,
    )
      .then((payload) => {
        if (!alive) return;
        if (!payload.timeseries) throw new Error("compare series missing");
        setCompareSeries(payload.timeseries);
        setError(false);
      })
      .catch(() => {
        if (alive) {
          setCompareSeries(null);
          setError(true);
        }
      });
    return () => {
      alive = false;
      controller.abort();
    };
  }, [key, view.compare, view.split, series]);

  if (!compareSeries || !series) return { overlay: null, error };
  const length = Math.min(series.points.length, compareSeries.points.length);
  const points = series.points
    .slice(0, length)
    .map((point, index) => ({
      name: point.bucket,
      count: point.count,
      prev: point.prev,
      series: point.series,
      compare: compareSeries.points[index]?.count ?? 0,
    }));
  return {
    overlay: {
      points,
      cropped: Math.max(0, compareSeries.points.length - length),
      padded: Math.max(0, series.points.length - length),
    },
    error,
  };
}
