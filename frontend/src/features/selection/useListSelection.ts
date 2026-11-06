import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/** Tri-state summary of one subset (a group header, a partition chip). */
export interface ListSelectionTriState {
  checked: boolean;
  mixed: boolean;
  count: number;
}

export interface UseListSelectionOptions {
  /** Every id the listing currently holds (the prune boundary). */
  allIds: string[];
  /** Ids passing the current search/filter, in render order (range target). */
  matchingIds: string[];
}

export interface ListSelection {
  active: boolean;
  /** Selected ids that still exist in the listing (stale ids are inert). */
  ids: ReadonlySet<string>;
  count: number;
  /** Selected ids filtered out by the current search/filter. */
  hiddenCount: number;
  enter: () => void;
  exit: () => void;
  clear: () => void;
  isSelected: (id: string) => boolean;
  toggle: (id: string, options?: { range?: boolean }) => void;
  /** Add or remove a set of ids without touching the rest of the selection. */
  setSelection: (ids: string[], selected: boolean) => void;
  triState: (ids: string[]) => ListSelectionTriState;
  dropHidden: () => void;
}

/**
 * Selection state for one listing (plan 200). Ids in, ids out: no fetching,
 * no router, no data knowledge. The caller owns `allIds`/`matchingIds` and
 * decides which scopes to offer; the hook only tracks the set, range anchors
 * and the hidden-by-filter count.
 */
export function useListSelection({
  allIds,
  matchingIds,
}: UseListSelectionOptions): ListSelection {
  const [active, setActive] = useState(false);
  const [raw, setRaw] = useState<ReadonlySet<string>>(() => new Set<string>());
  const anchor = useRef<string | null>(null);

  const allKey = allIds.join("\u0000");
  const matchingKey = matchingIds.join("\u0000");
  const allSet = useMemo(
    () => new Set(allKey === "" ? [] : allKey.split("\u0000")),
    [allKey]
  );
  const matchingSet = useMemo(
    () => new Set(matchingKey === "" ? [] : matchingKey.split("\u0000")),
    [matchingKey]
  );

  useEffect(() => {
    anchor.current = null;
  }, [matchingKey]);

  const ids = useMemo(() => {
    const kept = new Set<string>();
    for (const id of raw) {
      if (allSet.has(id)) kept.add(id);
    }
    return kept;
  }, [raw, allSet]);

  const hiddenCount = useMemo(() => {
    let hidden = 0;
    for (const id of ids) {
      if (!matchingSet.has(id)) hidden += 1;
    }
    return hidden;
  }, [ids, matchingSet]);

  const enter = useCallback(() => {
    anchor.current = null;
    setActive(true);
  }, []);

  const exit = useCallback(() => {
    anchor.current = null;
    setActive(false);
    setRaw(new Set<string>());
  }, []);

  const clear = useCallback(() => {
    anchor.current = null;
    setRaw(new Set<string>());
  }, []);

  const isSelected = useCallback((id: string) => ids.has(id), [ids]);

  const toggle = useCallback(
    (id: string, options?: { range?: boolean }) => {
      const target = !ids.has(id);
      const from = anchor.current;
      const start = from === null ? -1 : matchingIds.indexOf(from);
      const end = matchingIds.indexOf(id);
      if (options?.range && start !== -1 && end !== -1 && from !== id) {
        const [low, high] = start <= end ? [start, end] : [end, start];
        const span = matchingIds.slice(low, high + 1);
        setRaw((prev) => {
          const next = new Set(prev);
          for (const entry of span) {
            if (target) next.add(entry);
            else next.delete(entry);
          }
          return next;
        });
      } else {
        setRaw((prev) => {
          const next = new Set(prev);
          if (target) next.add(id);
          else next.delete(id);
          return next;
        });
      }
      anchor.current = id;
    },
    [ids, matchingIds]
  );

  const setSelection = useCallback((targets: string[], selected: boolean) => {
    setRaw((prev) => {
      const next = new Set(prev);
      for (const id of targets) {
        if (selected) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }, []);

  const triState = useCallback(
    (targets: string[]): ListSelectionTriState => {
      let count = 0;
      for (const id of targets) {
        if (ids.has(id)) count += 1;
      }
      const checked = targets.length > 0 && count === targets.length;
      return { checked, mixed: count > 0 && !checked, count };
    },
    [ids]
  );

  const dropHidden = useCallback(() => {
    setRaw((prev) => {
      const next = new Set<string>();
      for (const id of prev) {
        if (matchingSet.has(id)) next.add(id);
      }
      return next;
    });
  }, [matchingSet]);

  return {
    active,
    ids,
    count: ids.size,
    hiddenCount,
    enter,
    exit,
    clear,
    isSelected,
    toggle,
    setSelection,
    triState,
    dropHidden,
  };
}
