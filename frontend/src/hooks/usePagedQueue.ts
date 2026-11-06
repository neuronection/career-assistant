import { useCallback, useEffect, useRef, useState } from "react";

import { apiDetail } from "@/api/client";

/** One window of a keyset-paged queue (the admin queue contract, plan 206). */
export interface PagedQueuePage<T> {
  items: T[];
  next_cursor: string | null;
  total: number | null;
}

interface PagedQueueState<T> {
  items: T[];
  cursor: string | null;
  total: number | null;
  loading: boolean;
  loadingMore: boolean;
}

export interface PagedQueue<T> extends PagedQueueState<T> {
  /** Refetch the first window (filter changes, explicit refresh). */
  refresh: () => Promise<void>;
  /** Append the next window; a no-op without a cursor or while in flight. */
  loadMore: () => Promise<void>;
  /** Drop reviewed rows locally and top the window back up when it shrinks. */
  remove: (ids: string[]) => void;
}

/**
 * Keyset paging for one queue listing: the first window, the appended
 * windows and the opaque cursor between them. The hook owns no fetching
 * policy — the caller passes `fetchPage(cursor)` and keeps its own error
 * surface through `onError`.
 *
 * `remove` exists because the queue's decisions are destructive: a reviewed
 * row leaves the list immediately instead of forcing a full reload that
 * throws away every loaded window. A sentinel already in view does not fire
 * again when content disappears above it, so a shrunken window is topped up
 * explicitly.
 */
export function usePagedQueue<T>({
  fetchPage,
  keyOf,
  pageSize,
  onError,
}: {
  fetchPage: (cursor: string | null) => Promise<PagedQueuePage<T>>;
  keyOf: (item: T) => string;
  pageSize: number;
  onError?: (message: string) => void;
}): PagedQueue<T> {
  const [state, setState] = useState<PagedQueueState<T>>({
    items: [],
    cursor: null,
    total: null,
    loading: true,
    loadingMore: false,
  });
  const stateRef = useRef(state);
  const fetchRef = useRef(fetchPage);
  const keyRef = useRef(keyOf);
  const errorRef = useRef(onError);
  const epoch = useRef(0);
  const inFlight = useRef(false);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);
  useEffect(() => {
    fetchRef.current = fetchPage;
    keyRef.current = keyOf;
    errorRef.current = onError;
  }, [fetchPage, keyOf, onError]);

  const refresh = useCallback(async () => {
    const token = ++epoch.current;
    setState((prev) => ({ ...prev, loading: prev.items.length === 0 }));
    try {
      const page = await fetchRef.current(null);
      if (token !== epoch.current) return;
      setState({
        items: page.items,
        cursor: page.next_cursor,
        total: page.total,
        loading: false,
        loadingMore: false,
      });
    } catch (err) {
      if (token !== epoch.current) return;
      setState((prev) => ({ ...prev, loading: false }));
      errorRef.current?.(apiDetail(err));
    }
  }, []);

  const loadMore = useCallback(async () => {
    const current = stateRef.current;
    if (!current.cursor || inFlight.current) return;
    const token = epoch.current;
    inFlight.current = true;
    setState((prev) => ({ ...prev, loadingMore: true }));
    try {
      const page = await fetchRef.current(current.cursor);
      if (token !== epoch.current) return;
      setState((prev) => {
        const seen = new Set(prev.items.map((item) => keyRef.current(item)));
        const appended = page.items.filter((item) => !seen.has(keyRef.current(item)));
        return {
          items: [...prev.items, ...appended],
          cursor: page.next_cursor,
          total: page.total ?? prev.total,
          loading: false,
          loadingMore: false,
        };
      });
    } catch (err) {
      if (token !== epoch.current) return;
      setState((prev) => ({ ...prev, loadingMore: false }));
      errorRef.current?.(apiDetail(err));
    } finally {
      inFlight.current = false;
    }
  }, []);

  const remove = useCallback(
    (ids: string[]) => {
      if (ids.length === 0) return;
      const drop = new Set(ids);
      const current = stateRef.current;
      const remaining = current.items.filter((item) => !drop.has(keyRef.current(item)));
      const removed = current.items.length - remaining.length;
      if (removed === 0) return;
      setState((prev) => ({
        ...prev,
        items: remaining,
        total: prev.total == null ? null : Math.max(0, prev.total - removed),
      }));
      if (remaining.length < pageSize && current.cursor) {
        void loadMore();
      }
    },
    [loadMore, pageSize]
  );

  return { ...state, refresh, loadMore, remove };
}
