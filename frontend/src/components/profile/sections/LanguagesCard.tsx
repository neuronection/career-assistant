import { forwardRef } from "react";
import { useTranslation } from "react-i18next";
import i18next from "i18next";
import { Link } from "react-router-dom";
import { Award, X } from "lucide-react";
import {
  ComboboxField,
  FormRow,
  SegmentedRow,
} from "@/components/cv/formPrimitives";
import { ProfileSectionCard } from "@/components/profile/ProfileSectionCard";
import type { Profile } from "@/types";
import { LANGUAGE_CODE_OPTIONS, LANGUAGE_LEVELS } from "./options";
import {
  useSectionCard,
  type SectionCardBaseProps,
  type SectionCardHandle,
} from "./shared";

export interface LanguagesCardProps
  extends SectionCardBaseProps<Profile["academics"]> {}

function validateLanguages(languages: Profile["academics"]["languages"]): string[] {
  return languages.map((l) =>
    l.code ? "" : i18next.t("profile.validation.pickLanguage")
  );
}

/**
 * Languages as their own profile section (2026-09 split out of Study
 * preferences): level rows plus a per-language "Add certificate" entry
 * that deep-links the education workspace's certification editor with
 * the language pre-filled.
 */
export const LanguagesCard = forwardRef<SectionCardHandle, LanguagesCardProps>(
  function LanguagesCard(
    { initial, onSave, mode = "autosave", variant = "page", complete = null },
    ref
  ) {
    const { t } = useTranslation();
    const { draft, setDraft, state, error } = useSectionCard(ref, {
      initial,
      onSave,
      mode,
      buildPayload: (d) => ({
        academics: { ...d, favorite_subjects: initial.favorite_subjects },
      }),
      isValid: (d) => validateLanguages(d.languages).every((msg) => !msg),
    });
    const rowErrors = validateLanguages(draft.languages);
    const patch = (partial: Partial<Profile["academics"]>) =>
      setDraft({ ...draft, ...partial });

    return (
      <ProfileSectionCard
        name="languages"
        title={t("profileSection.languagesTitle")}
        description={
          variant === "page" ? t("profileSection.languagesBody") : undefined
        }
        complete={complete}
        saveState={state}
        error={error}
        variant={variant}
      >
        <div className="space-y-2">
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
                {lang.code !== "" && (
                  <Link
                    to={`/profile/education?entity=certifications&new=1&language=${encodeURIComponent(lang.code)}`}
                    className="inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-md border border-[var(--as-border)] px-2 py-1 text-xs text-[var(--as-muted-fg)] transition-colors hover:border-[var(--as-accent)] hover:text-[var(--as-fg)]"
                    aria-label={t("profileSection.addCertificateFor", {
                      language: t(
                        `language.${lang.code}`,
                        { defaultValue: lang.code }
                      ),
                    })}
                    title={t("profileSection.addCertificateFor", {
                      language: t(`language.${lang.code}`, {
                        defaultValue: lang.code,
                      }),
                    })}
                    data-testid={`language-certificate-${i}`}
                  >
                    <Award className="h-3.5 w-3.5" aria-hidden />
                    {t("profileSection.addCertificate")}
                  </Link>
                )}
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
      </ProfileSectionCard>
    );
  }
);
