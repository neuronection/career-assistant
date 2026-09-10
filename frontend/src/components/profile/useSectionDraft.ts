import { useCallback, useEffect, useRef, useState } from "react";
import { apiDetail } from "@/api/client";
import type { Profile } from "@/types";
import type { SectionSaveState } from "./ProfileSectionCard";

export interface UseSectionDraftOptions<T> {
  initial: T;
  buildPayload: (draft: T) => Partial<Profile> | null;
  onSave: (payload: Partial<Profile>) => Promise<void>;
  mode?: "autosave" | "manual";
  delay?: number;
  isValid?: (draft: T) => boolean;
}

export interface SectionDraft<T> {
  draft: T;
  setDraft: (updater: T | ((prev: T) => T)) => void;
  state: SectionSaveState;
  error: string;
  dirty: boolean;
  save: () => Promise<boolean>;
}

/** Draft state + dirty tracking + debounced autosave for one profile
 * section (the CV builder's 500ms pattern, timer cleared on unmount).
 * `mode="manual"` skips autosave — the wizard flushes via `save()`. */
export function useSectionDraft<T>({
  initial,
  buildPayload,
  onSave,
  mode = "autosave",
  delay = 500,
  isValid,
}: UseSectionDraftOptions<T>): SectionDraft<T> {
  const [draft, setDraftState] = useState<T>(initial);
  const [state, setState] = useState<SectionSaveState>("idle");
  const [error, setError] = useState("");
  const [dirty, setDirty] = useState(false);

  const draftRef = useRef<T>(initial);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const savedJsonRef = useRef<string>(JSON.stringify(buildPayload(initial) ?? null));
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
      setDirty(false);
      setState("idle");
      return true;
    }
    setState("saving");
    setError("");
    try {
      await save(payload);
      savedJsonRef.current = json;
      setDirty(false);
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
      const dirtyNow =
        JSON.stringify(optsRef.current.buildPayload(next) ?? null) !==
        savedJsonRef.current;
      setDirty(dirtyNow);
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
    const nextJson = JSON.stringify(
      optsRef.current.buildPayload(initial) ?? null
    );
    if (nextJson === savedJsonRef.current) return;
    if (dirty) return;
    savedJsonRef.current = nextJson;
    draftRef.current = initial;
    setDraftState(initial);
    setDirty(false);
    setState("idle");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  return { draft, setDraft, state, error, dirty, save: flush };
}
