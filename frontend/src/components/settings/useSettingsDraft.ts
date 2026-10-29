import { useCallback, useEffect, useRef, useState } from "react";
import { apiDetail } from "@/api/client";
import type { SettingsSaveState } from "@/components/settings/saveState";

export interface UseSettingsDraftOptions<T, P> {
  initial: T;
  /** Normalizes the draft into the wire payload; `null` = nothing to save
   * (a card whose draft cannot produce a payload never PUTs). */
  buildPayload: (draft: T) => P | null;
  onSave: (payload: P) => Promise<void>;
  /** autosave = debounced PUT while editing; manual = explicit save()
   * (forms with a Save button). */
  mode?: "autosave" | "manual";
  /** Debounce window for autosave (ms). */
  delay?: number;
  /** Invalid drafts never autosave; save() returns false. */
  isValid?: (draft: T) => boolean;
}

export interface SettingsDraft<T> {
  draft: T;
  setDraft: (updater: T | ((prev: T) => T)) => void;
  state: SettingsSaveState;
  error: string;
  dirty: boolean;
  save: () => Promise<boolean>;
}

/** Draft state + dirty tracking + debounced autosave for one settings
 * card — the profile `useSectionDraft` contract generalized to any wire
 * payload (plan 148's hybrid save semantics). Untouched drafts never PUT
 * (payload-JSON compare); the debounce timer is cleared on unmount;
 * external `initial` changes adopt while the user has no local edits.
 * A draft whose `buildPayload` returns `null` is "nothing to save": it
 * is never dirty and adopts external changes freely. Optimistic toggles
 * resolve per key in call order — user-paced switches are the contract;
 * machine-gun double toggles may resolve out of order. */
export function useSettingsDraft<T, P>({
  initial,
  buildPayload,
  onSave,
  mode = "manual",
  delay = 500,
  isValid,
}: UseSettingsDraftOptions<T, P>): SettingsDraft<T> {
  const [draft, setDraftState] = useState<T>(initial);
  const [state, setState] = useState<SettingsSaveState>("idle");
  const [error, setError] = useState("");

  const draftRef = useRef<T>(initial);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const savedJsonRef = useRef<string | undefined>(undefined);
  if (savedJsonRef.current === undefined) {
    savedJsonRef.current = JSON.stringify(buildPayload(initial) ?? null);
  }
  const optsRef = useRef({ buildPayload, onSave, isValid, mode, delay });
  optsRef.current = { buildPayload, onSave, isValid, mode, delay };

  const flush = useCallback(async (): Promise<boolean> => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    const { buildPayload: build, onSave: save, isValid: valid } = optsRef.current;
    const current = draftRef.current;
    if (valid && !valid(current)) {
      setState("dirty");
      return false;
    }
    const payload = build(current);
    if (!payload) {
      setState("idle");
      return true;
    }
    const json = JSON.stringify(payload);
    if (json === savedJsonRef.current) {
      setState("idle");
      return true;
    }
    setState("saving");
    setError("");
    try {
      await save(payload);
      savedJsonRef.current = json;
      setState("saved");
      return true;
    } catch (err) {
      setError(apiDetail(err));
      setState("error");
      return false;
    }
  }, []);

  const setDraft = useCallback(
    (updater: T | ((prev: T) => T)) => {
      const next =
        typeof updater === "function"
          ? (updater as (prev: T) => T)(draftRef.current)
          : updater;
      draftRef.current = next;
      setDraftState(next);
      const payload = optsRef.current.buildPayload(next);
      const dirtyNow =
        payload !== null && JSON.stringify(payload) !== savedJsonRef.current;
      setState(dirtyNow ? "dirty" : "idle");
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      if (dirtyNow && optsRef.current.mode === "autosave") {
        timerRef.current = setTimeout(() => void flush(), optsRef.current.delay);
      }
    },
    [flush]
  );

  useEffect(() => {
    const nextJson = JSON.stringify(optsRef.current.buildPayload(initial) ?? null);
    if (nextJson === savedJsonRef.current) return;
    const currentJson = JSON.stringify(
      optsRef.current.buildPayload(draftRef.current) ?? null
    );
    if (currentJson !== savedJsonRef.current) return;
    savedJsonRef.current = nextJson;
    draftRef.current = initial;
    setDraftState(initial);
    setState("idle");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const currentPayload = optsRef.current.buildPayload(draft);
  const dirtyDerived =
    currentPayload !== null &&
    JSON.stringify(currentPayload) !== savedJsonRef.current;

  return { draft, setDraft, state, error, dirty: dirtyDerived, save: flush };
}

/** Instant-toggle companion for the hybrid save contract: the switch
 * flips optimistically, the commit runs; a rejected commit rolls the
 * switch back and flags the key as failing until the next attempt. */
export function useOptimisticToggle() {
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});
  const [failed, setFailed] = useState<Record<string, true>>({});

  const toggle = useCallback(
    async (key: string, next: boolean, commit: () => Promise<unknown>) => {
      setFailed((prev) => {
        if (!prev[key]) return prev;
        const rest = { ...prev };
        delete rest[key];
        return rest;
      });
      setOverrides((prev) => ({ ...prev, [key]: next }));
      try {
        await commit();
      } catch {
        setOverrides((prev) => {
          const rest = { ...prev };
          delete rest[key];
          return rest;
        });
        setFailed((prev) => ({ ...prev, [key]: true }));
      }
    },
    []
  );

  const valueOf = useCallback(
    (key: string, persisted: boolean) => overrides[key] ?? persisted,
    [overrides]
  );

  const isFailing = useCallback((key: string) => failed[key] === true, [failed]);

  return { toggle, valueOf, isFailing };
}
