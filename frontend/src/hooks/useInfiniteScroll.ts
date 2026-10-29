import { useEffect, useRef } from "react";

/**
 * Auto-load sentinel (plan 141): observes the returned sentinel element
 * and calls `loadMore` when it comes within 480px of the viewport.
 * `loadMore` may return a promise — an in-flight call blocks re-entry
 * until it settles. Re-observes whenever `loadMore` (its identity moves
 * with the paging cursor) or `enabled` changes.
 */
export function useInfiniteScroll(
  loadMore: () => Promise<unknown> | unknown,
  enabled: boolean,
) {
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const loadingRef = useRef(false);
  const callbackRef = useRef(loadMore);

  useEffect(() => {
    callbackRef.current = loadMore;
  }, [loadMore]);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || !enabled) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting) || loadingRef.current) return;
        loadingRef.current = true;
        Promise.resolve(callbackRef.current()).finally(() => {
          loadingRef.current = false;
        });
      },
      { rootMargin: "480px 0px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [enabled, loadMore]);

  return sentinelRef;
}
