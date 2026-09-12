import { forwardRef } from "react";
import { useTranslation } from "react-i18next";
import i18next from "i18next";
import { X } from "lucide-react";
import {
  ComboboxField,
  ComboboxMultiField,
  FormRow,
  SegmentedRow,
  StepperRow,
} from "@/components/cv/formPrimitives";
import { ProfileSectionCard } from "@/components/profile/ProfileSectionCard";
import type { Profile } from "@/types";
import {
  COMMON_SUBJECTS,
  LANGUAGE_CODE_OPTIONS,
  LANGUAGE_LEVELS,
} from "./options";
import {
  useSectionCard,
  type SectionCardBaseProps,
  type SectionCardHandle,
} from "./shared";

export interface AcademicsCardProps
  extends SectionCardBaseProps<Profile["academics"]> {}

function validateAcademics(draft: Profile["academics"]): {
  languageRow: string[];
} {
  return {
    languageRow: draft.languages.map((l) =>
      l.code ? "" : i18next.t("profile.validation.pickLanguage")
    ),
  };
}

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
      buildPayload: (d) => ({ academics: d }),
      isValid: (d) => validateAcademics(d).languageRow.every((msg) => !msg),
    });
    const rowErrors = validateAcademics(draft).languageRow;
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
        <div className="space-y-5">
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

          <div className="space-y-2">
            <p className="text-xs text-[var(--as-muted-fg)]">{t("profileSection.languages")}</p>
            {draft.languages.map((lang, i) => (
              <FormRow
                key={i}
                error={rowErrors[i] || undefined}
                testId={`academics-language-${i}`}
              >
                <div className="flex flex-wrap items-end gap-2 rounded-lg border border-[var(--as-border)] p-2.5">
                  <div className="w-44">
                    <ComboboxField
                      label={t("profileSection.language")}
                      value={lang.code}
                      options={LANGUAGE_CODE_OPTIONS.map((o) => ({
                        value: o.value,
                        label: t(o.labelKey, { defaultValue: o.label }),
                      }))}
                      allowCreate
                      createLabel={(term) =>
                        t("profileSection.addNamedLanguage", { name: term })
                      }
                      testId={`language-code-${i}`}
                      onChange={(code) =>
                        patch({
                          languages: draft.languages.map((x, j) =>
                            j === i ? { ...x, code: code.toLowerCase() } : x
                          ),
                        })
                      }
                    />
                  </div>
                  <div className="min-w-0 flex-1">
                    <SegmentedRow
                      label={t("education.levelLabel")}
                      value={lang.level}
                      options={LANGUAGE_LEVELS.map((o) => ({
                        value: o.value,
                        label: t(o.labelKey, { defaultValue: o.label }),
                      }))}
                      onChange={(level) =>
                        patch({
                          languages: draft.languages.map((x, j) =>
                            j === i ? { ...x, level } : x
                          ),
                        })
                      }
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      patch({
                        languages: draft.languages.filter((_, j) => j !== i),
                      })
                    }
                    className="cursor-pointer rounded-md p-1 text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-danger)]"
                    aria-label={t("profileSection.removeLanguage")}
                    data-testid={`language-remove-${i}`}
                  >
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </div>
              </FormRow>
            ))}
            <button
              type="button"
              onClick={() =>
                patch({
                  languages: [
                    ...draft.languages,
                    { code: "", level: "intermediate" },
                  ],
                })
              }
              className="cursor-pointer rounded-lg border border-dashed border-[var(--as-border)] px-3 py-1.5 text-xs text-[var(--as-muted-fg)] transition-colors hover:border-[var(--as-accent)] hover:text-[var(--as-fg)]"
              data-testid="add-language"
            >
              {t("profileSection.addLanguage")}
            </button>
          </div>
        </div>
      </ProfileSectionCard>
    );
  }
);
