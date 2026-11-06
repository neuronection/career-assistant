import { useCallback, useEffect, useRef, useState } from "react";

import { fetchPostingStatsDashboard, type MarketDashboard } from "@/api/stats";
import { dashboardParams, type MarketStatsView } from "../marketStatsParams";

/** One composite request per view (plan 195): abortable, request-id
 * guarded and keep-previous-data on refetch — a filter change never
 * blanks the tab it is filtering. */
export function useDashboardQuery(view: MarketStatsView) {
  const [data, setData] = useState<MarketDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [nonce, setNonce] = useState(0);
  const requestId = useRef(0);
  const key = JSON.stringify(dashboardParams(view));

  const refresh = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    const id = ++requestId.current;
    const controller = new AbortController();
    setLoading(true);
    setFailed(false);
    fetchPostingStatsDashboard(
      JSON.parse(key) as Record<string, string | string[] | number | boolean>,
      controller.signal,
    )
      .then((payload) => {
        if (id !== requestId.current) return;
        setData(payload);
        setLoading(false);
      })
      .catch((error: unknown) => {
        if (id !== requestId.current || controller.signal.aborted) return;
        setFailed(true);
        setErrorMessage(error instanceof Error ? error.message : "request failed");
        setLoading(false);
      });
    return () => controller.abort();
  }, [key, nonce]);

  return { data, loading, failed, errorMessage, refresh };
}
