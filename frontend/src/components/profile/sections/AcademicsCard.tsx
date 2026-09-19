import { forwardRef } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import {
  ComboboxMultiField,
  StepperRow,
} from "@/components/cv/formPrimitives";
import { ProfileSectionCard } from "@/components/profile/ProfileSectionCard";
import type { Profile } from "@/types";
import { COMMON_SUBJECTS } from "./options";
import {
  useSectionCard,
  type SectionCardBaseProps,
  type SectionCardHandle,
} from "./shared";

export interface AcademicsCardProps
  extends SectionCardBaseProps<Profile["academics"]> {}

export const AcademicsCard = forwardRef<SectionCardHandle, AcademicsCardProps>(
  function AcademicsCard(
    { initial, onSave, mode = "autosave", variant = "page", complete = null },
    ref
  ) {
    const { t } = useTranslation();
    const { draft, setDraft, state, error } = useSectionCard(ref, {
      initial,
      onSave,
      mode,
      buildPayload: (d) => ({
        academics: { ...d, languages: initial.languages },
      }),
    });
    const patch = (partial: Partial<Profile["academics"]>) =>
      setDraft({ ...draft, ...partial });

    const subjectOptions = COMMON_SUBJECTS.map((s) => ({
      value: s,
      label: t(`education.subject.${s}`, {
        defaultValue: s.replace(/-/g, " "),
      }),
    }));

    const setSubjects = (keys: string[]) => {
      const subjects = keys.map((key) => {
        const existing = draft.favorite_subjects.find((s) => s.key === key);
        return { key, weight: existing?.weight ?? 3 };
      });
      patch({ favorite_subjects: subjects });
    };

    return (
      <ProfileSectionCard
        name="academics"
        title={t("onboarding.step.studyPreferences")}
        description={
          variant === "page"
            ? t("profileSection.academicsBody")
            : undefined
        }
        complete={complete}
        saveState={state}
        error={error}
        variant={variant}
      >
        <div className="space-y-2">
          <ComboboxMultiField
            label={t("profileSection.favoriteSubjects")}
            values={draft.favorite_subjects.map((s) => s.key)}
            onChange={setSubjects}
            options={subjectOptions}
            maxTriggerLabels={4}
            testId="academics-subjects"
          />
          {draft.favorite_subjects.length > 0 && (
            <div className="space-y-1.5 rounded-lg border border-[var(--as-border)] p-2.5">
              {draft.favorite_subjects.map((s) => (
                <div key={s.key} className="flex items-center gap-2">
                  <span className="w-32 shrink-0 truncate text-xs capitalize text-[var(--as-fg)]">
                    {s.key.replace(/-/g, " ")}
                  </span>
                  <div className="min-w-0 flex-1">
                    <StepperRow
                      label={t("profileSection.subjectWeight", {
                        subject: t(`education.subject.${s.key}`, {
                          defaultValue: s.key.replace(/-/g, " "),
                        }),
                      })}
                      value={s.weight}
                      min={1}
                      max={5}
                      suffix="1–5"
                      onChange={(weight) =>
                        patch({
                          favorite_subjects: draft.favorite_subjects.map((x) =>
                            x.key === s.key ? { ...x, weight } : x
                          ),
                        })
                      }
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      setSubjects(
                        draft.favorite_subjects
                          .map((x) => x.key)
                          .filter((k) => k !== s.key)
                      )
                    }
                    className="shrink-0 cursor-pointer rounded-md p-1 text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-danger)]"
                    aria-label={t("profileSection.removeSubject", {
                      subject: t(`education.subject.${s.key}`, {
                        defaultValue: s.key.replace(/-/g, " "),
                      }),
                    })}
                    data-testid={`subject-remove-${s.key}`}
                  >
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </ProfileSectionCard>
    );
  }
);
