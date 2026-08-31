import { useEffect, useRef } from "react";
import { recordSearch } from "@/api/engagement";
import type { SearchScope } from "@/types";

/** Records searches server-side (the server debounces 30-min repeats). */
export function useSearchHistory(scope: SearchScope) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const record = (
    query: string,
    filters: Record<string, unknown>,
    resultCount: number
  ) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      void recordSearch({ scope, query, filters, result_count: resultCount }).catch(
        () => undefined
      );
    }, 1200);
  };

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    []
  );

  return record;
}
