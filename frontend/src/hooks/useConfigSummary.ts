import { useEffect, useState } from "react";

import { fetchConfigSummary, type ConfigSummary } from "@/api/ai";
import { useAuthStore } from "@/stores/authStore";

/** Stable identity for the effective-assignment summary query. */
export const AI_CONFIG_SUMMARY_QUERY_KEY = ["ai-config-summary"] as const;

/** Assignments change from Settings only; the floating chat re-mounts often. */
export const AI_CONFIG_SUMMARY_STALE_TIME_MS = 5 * 60_000;

interface SummarySnapshot {
  data: ConfigSummary | null;
  error: unknown | null;
  loading: boolean;
}

const CACHE_KEY = AI_CONFIG_SUMMARY_QUERY_KEY.join("/");
const cache = new Map<string, { data: ConfigSummary; fetchedAt: number }>();
const inFlight = new Map<string, Promise<ConfigSummary>>();
const listeners = new Set<() => void>();
let generation = 0;

function freshEntry(key: string): ConfigSummary | null {
  const entry = cache.get(key);
  if (entry === undefined) return null;
  if (Date.now() - entry.fetchedAt >= AI_CONFIG_SUMMARY_STALE_TIME_MS) return null;
  return entry.data;
}

/**
 * Drop the shared cache after a settings change.
 *
 * Bumps the generation so a request already in flight cannot repopulate
 * the cache or overwrite the new snapshot, then wakes every mounted
 * consumer so it re-reads the effective assignment.
 */
export function resetConfigSummaryCache(): void {
  generation += 1;
  cache.clear();
  inFlight.clear();
  for (const listener of listeners) listener();
}

function subscribeConfigSummary(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Read the caller's effective AI assignment per task.
 *
 * One shared module cache backs every mount: the floating chat widget asks
 * on mount, and a fresh entry answers without a request. A failed request
 * surfaces `error` and never fabricates an assignment, so capability gates
 * keep the unknown (mic) state instead of locking the user out.
 */
export function useConfigSummary(): SummarySnapshot {
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const cacheKey = `${CACHE_KEY}:${userId ?? "anonymous"}`;
  const [epoch, setEpoch] = useState(generation);
  const [snapshot, setSnapshot] = useState<SummarySnapshot>(() => {
    const data = freshEntry(cacheKey);
    return { data, error: null, loading: data === null };
  });

  useEffect(
    () => subscribeConfigSummary(() => setEpoch(generation)),
    [],
  );

  useEffect(() => {
    const cached = freshEntry(cacheKey);
    if (cached !== null) {
      setSnapshot({ data: cached, error: null, loading: false });
      return;
    }
    let active = true;
    const requestGeneration = generation;
    setSnapshot({ data: null, error: null, loading: true });
    const request = inFlight.get(cacheKey) ?? fetchConfigSummary();
    inFlight.set(cacheKey, request);
    request
      .then((data) => {
        if (requestGeneration !== generation) return;
        cache.set(cacheKey, { data, fetchedAt: Date.now() });
        if (inFlight.get(cacheKey) === request) inFlight.delete(cacheKey);
        if (active) setSnapshot({ data, error: null, loading: false });
      })
      .catch((error: unknown) => {
        if (requestGeneration !== generation) return;
        if (inFlight.get(cacheKey) === request) inFlight.delete(cacheKey);
        if (active) {
          setSnapshot({
            data: null,
            error,
            loading: false,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [cacheKey, epoch]);

  return snapshot;
}
