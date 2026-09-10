import { forwardRef } from "react";
import { useTranslation } from "react-i18next";
import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";
import {
  ComboboxMultiField,
  TextField,
  TextareaField,
} from "@/components/cv/formPrimitives";
import { ProfileSectionCard } from "@/components/profile/ProfileSectionCard";
import { useProfileStore } from "@/stores/profileStore";
import type { Profile } from "@/types";
import {
  useSectionCard,
  type SectionCardBaseProps,
  type SectionCardHandle,
} from "./shared";

export interface AspirationsCardProps
  extends SectionCardBaseProps<Profile["aspirations"]> {}

export const AspirationsCard = forwardRef<SectionCardHandle, AspirationsCardProps>(
  function AspirationsCard(
    { initial, onSave, mode = "autosave", variant = "page", complete = null },
    ref
  ) {
    const taxonomy = useProfileStore((s) => s.interests);
    const { t } = useTranslation();
    const { draft, setDraft, state, error } = useSectionCard(ref, {
      initial,
      onSave,
      mode,
      buildPayload: (d) => ({ aspirations: d }),
    });

    const tagOptions = taxonomy.map((t) => ({ value: t.key, label: t.label }));

    const patchRow = (index: number, partial: Partial<Profile["aspirations"][number]>) =>
      setDraft(
        draft.map((row, i) => (i === index ? { ...row, ...partial } : row))
      );

    const move = (index: number, delta: -1 | 1) => {
      const next = [...draft];
      const target = index + delta;
      if (target < 0 || target >= next.length) return;
      [next[index], next[target]] = [next[target], next[index]];
      setDraft(next);
    };

    return (
      <ProfileSectionCard
        name="aspirations"
        title={t("onboarding.step.aspirations")}
        description={
          variant === "page"
            ? t("profileSection.aspirationsBody")
            : undefined
        }
        complete={complete}
        saveState={state}
        error={error}
        variant={variant}
      >
        <div className="space-y-3">
          {draft.map((row, i) => (
            <div
              key={i}
              className="space-y-2.5 rounded-lg border border-[var(--as-border)] p-3"
              data-testid={`aspiration-row-${i}`}
            >
              <div className="flex items-center gap-2">
                <div className="min-w-0 flex-1">
                  <TextField
                    label={t("profileSection.aspirationN", { index: i + 1 })}
                    value={row.label}
                    onChange={(label) => patchRow(i, { label })}
                    maxLength={200}
                    placeholder={t("profileSection.aspirationPlaceholder")}
                    testId={`aspiration-label-${i}`}
                  />
                </div>
                <div className="flex shrink-0 items-center gap-0.5 pt-4">
                  <button
                    type="button"
                    onClick={() => move(i, -1)}
                    disabled={i === 0}
                    className="cursor-pointer rounded-md border border-[var(--as-border)] p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] disabled:pointer-events-none disabled:opacity-40"
                    aria-label={t("profileSection.moveUpName", {
                      name: row.label || t("profileSection.aspirationName", { index: i + 1 }),
                    })}
                    data-testid={`aspiration-up-${i}`}
                  >
                    <ArrowUp className="h-3.5 w-3.5" aria-hidden />
                  </button>
                  <button
                    type="button"
                    onClick={() => move(i, 1)}
                    disabled={i === draft.length - 1}
                    className="cursor-pointer rounded-md border border-[var(--as-border)] p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] disabled:pointer-events-none disabled:opacity-40"
                    aria-label={t("profileSection.moveDownName", {
                      name: row.label || t("profileSection.aspirationName", { index: i + 1 }),
                    })}
                    data-testid={`aspiration-down-${i}`}
                  >
                    <ArrowDown className="h-3.5 w-3.5" aria-hidden />
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setDraft(draft.filter((_, j) => j !== i))
                    }
                    className="cursor-pointer rounded-md p-1 text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-danger)]"
                    aria-label={t("profileSection.removeName", {
                      name: row.label || t("profileSection.aspirationName", { index: i + 1 }),
                    })}
                    data-testid={`aspiration-remove-${i}`}
                  >
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </div>
              </div>
              <ComboboxMultiField
                label={t("profileSection.relatedInterests")}
                values={row.tag_keys}
                onChange={(tag_keys) => patchRow(i, { tag_keys })}
                options={tagOptions}
                maxTriggerLabels={4}
                testId={`aspiration-tags-${i}`}
              />
              <TextareaField
                label={t("profileSection.notes")}
                value={row.notes}
                onChange={(notes) => patchRow(i, { notes })}
                rows={2}
                maxLength={500}
                counter
                placeholder={t("profileSection.notesPlaceholder")}
                testId={`aspiration-notes-${i}`}
              />
            </div>
          ))}
          <button
            type="button"
            onClick={() =>
              setDraft([...draft, { label: "", tag_keys: [], notes: "" }])
            }
            className="w-full cursor-pointer rounded-lg border border-dashed border-[var(--as-border)] px-3 py-2 text-xs text-[var(--as-muted-fg)] transition-colors hover:border-[var(--as-accent)] hover:text-[var(--as-fg)]"
            data-testid="add-aspiration"
          >
            <Plus className="mr-1 inline h-3.5 w-3.5" aria-hidden />
            {t("profileSection.addAspiration")}
          </button>
        </div>
      </ProfileSectionCard>
    );
  }
);
