import { useImperativeHandle, type Ref } from "react";
import { useSectionDraft, type SectionDraft } from "@/components/profile/useSectionDraft";
import type { Profile } from "@/types";

export interface SectionCardHandle {
  save: () => Promise<boolean>;
  isDirty: () => boolean;
}

export interface SectionCardBaseProps<T> {
  initial: T;
  onSave: (payload: Partial<Profile>) => Promise<void>;
  mode?: "autosave" | "manual";
  variant?: "page" | "onboarding";
  complete?: boolean | null;
}

export function useSectionCard<T>(
  ref: Ref<SectionCardHandle>,
  props: SectionCardBaseProps<T> & {
    buildPayload: (draft: T) => Partial<Profile> | null;
    isValid?: (draft: T) => boolean;
  }
): SectionDraft<T> {
  const { buildPayload, isValid, ...base } = props;
  const section = useSectionDraft<T>({ ...base, buildPayload, isValid });
  useImperativeHandle(
    ref,
    () => ({ save: () => section.save(), isDirty: () => section.dirty }),
    [section.save, section.dirty]
  );
  return section;
}
