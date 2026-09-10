import { forwardRef } from "react";
import { useTranslation } from "react-i18next";
import i18next from "i18next";
import { X } from "lucide-react";
import {
  EmailField,
  FormRow,
  OptionalStepper,
  SelectField,
  TextField,
} from "@/components/cv/formPrimitives";
import { ProfileSectionCard } from "@/components/profile/ProfileSectionCard";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import type { CareerStage, Profile, ProfileLink, ProfileLinkKind } from "@/types";
import {
  EDUCATION_OPTIONS,
  LINK_KIND_OPTIONS,
  STAGE_OPTIONS,
} from "./options";
import {
  useSectionCard,
  type SectionCardBaseProps,
  type SectionCardHandle,
} from "./shared";

const CURRENT_YEAR = new Date().getFullYear();
const BIRTH_MIN = CURRENT_YEAR - 80;
const BIRTH_MAX = CURRENT_YEAR - 14;
const MAX_LINKS = 8;

export function validateBasics(draft: Profile["basics"]): {
  email?: string;
  linkRow: string[];
} {
  const errors: { email?: string; linkRow: string[] } = {
    linkRow: (draft.links ?? []).map((link) =>
      !link.url.trim()
        ? i18next.t("profile.validation.enterUrl")
        : /^https?:\/\//i.test(link.url.trim())
          ? ""
          : i18next.t("profile.validation.fullUrl")
    ),
  };
  const email =
    draft.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(draft.email.trim())
      ? i18next.t("profile.validation.email")
      : null;
  if (email) errors.email = email;
  return errors;
}

export interface BasicsCardProps
  extends SectionCardBaseProps<Profile["basics"]> {
  stageMode?: "section" | "endpoint";
  onStageChange?: (stage: CareerStage | null) => Promise<void>;
}

export const BasicsCard = forwardRef<SectionCardHandle, BasicsCardProps>(
  function BasicsCard(
    {
      initial,
      onSave,
      mode = "autosave",
      variant = "page",
      complete = null,
      stageMode = "section",
      onStageChange,
    },
    ref
  ) {
    const { t } = useTranslation();
    const gradeFields = useBootstrapStore(
      (s) => s.bootstrap?.features.grade_fields ?? false
    );
    const { draft, setDraft, state, error } = useSectionCard(ref, {
      initial,
      onSave,
      mode,
      buildPayload: (d) => ({ basics: d }),
      isValid: (d) => {
        const errors = validateBasics(d);
        return !errors.email && errors.linkRow.every((msg) => !msg);
      },
    });
    const errors = validateBasics(draft);
    const patch = (partial: Partial<Profile["basics"]>) =>
      setDraft({ ...draft, ...partial });
    const links = draft.links ?? [];
    const patchLink = (index: number, partial: Partial<ProfileLink>) =>
      patch({
        links: links.map((link, i) => (i === index ? { ...link, ...partial } : link)),
      });

    return (
      <ProfileSectionCard
        name="basics"
        title={
          variant === "onboarding"
            ? t(`profile.stageSubtitle.${draft.career_stage ?? "student"}`)
            : t("profileSection.basics")
        }
        description={
          variant === "page"
            ? t("profileSection.basicsBody")
            : undefined
        }
        complete={complete}
        saveState={state}
        error={error}
        variant={variant}
      >
        <div className="grid gap-x-4 gap-y-4 sm:grid-cols-2">
          {variant === "onboarding" && (
            <div className="sm:col-span-2" data-testid="stage-question">
              <SelectField
                label={t("profileSection.stageQuestion")}
                value={draft.career_stage ?? ""}
                options={STAGE_OPTIONS.map((o) => ({
                  value: o.value,
                  label: t(o.labelKey, { defaultValue: o.label }),
                }))}
                testId="basics-stage"
                onChange={(v) => {
                  const stage = (v || null) as CareerStage | null;
                  if (stageMode === "endpoint" && onStageChange) {
                    void onStageChange(stage);
                    return;
                  }
                  patch({ career_stage: stage });
                }}
              />
            </div>
          )}
          <div className="sm:col-span-2">
            <TextField
              label={t("profileSection.headline")}
              value={draft.headline}
              onChange={(v) => patch({ headline: v })}
              maxLength={120}
              placeholder={t("profileSection.headlinePlaceholder")}
              hint={t("profileSection.headlineHint")}
              testId="basics-headline"
            />
          </div>
          <EmailField
            label={t("profileSection.email")}
            value={draft.email}
            onChange={(v) => patch({ email: v })}
            placeholder="you@example.com"
            hint={t("profileSection.emailHint")}
            error={errors.email}
            testId="basics-email"
          />
          <TextField
            label={t("profileSection.phone")}
            type="tel"
            inputMode="tel"
            value={draft.phone}
            onChange={(v) => patch({ phone: v })}
            maxLength={40}
            placeholder="+30 69…"
            hint={t("profileSection.phoneHint")}
            testId="basics-phone"
          />
          <TextField
            label={t("profileSection.city")}
            value={draft.city}
            onChange={(v) => patch({ city: v })}
            maxLength={80}
            placeholder="Athens"
            testId="basics-city"
          />
          <TextField
            label={t("profileSection.country")}
            value={draft.country}
            onChange={(v) => patch({ country: v })}
            maxLength={80}
            placeholder="Greece"
            testId="basics-country"
          />
          <div className="sm:col-span-2 space-y-2">
            <p className="text-xs text-[var(--as-muted-fg)]">{t("profileSection.links")}</p>
            {links.map((link, i) => (
              <FormRow
                key={i}
                error={errors.linkRow[i] || undefined}
                testId={`basics-link-${i}`}
              >
                <div className="flex flex-wrap items-end gap-2 rounded-lg border border-[var(--as-border)] p-2.5">
                  <div className="w-36">
                    <SelectField
                      label={t("profileSection.linkType")}
                      value={link.kind}
                      options={LINK_KIND_OPTIONS.map((o) => ({
                        value: o.value,
                        label: t(o.labelKey, { defaultValue: o.label }),
                      }))}
                      testId={`link-kind-${i}`}
                      onChange={(v) =>
                        patchLink(i, { kind: v as ProfileLinkKind })
                      }
                    />
                  </div>
                  <div className="min-w-0 flex-1">
                    <TextField
                      label={t("profileSection.url")}
                      value={link.url}
                      onChange={(v) => patchLink(i, { url: v })}
                      maxLength={500}
                      placeholder="https://github.com/…"
                      testId={`link-url-${i}`}
                    />
                  </div>
                  <div className="w-40">
                    <TextField
                      label={t("profileSection.linkLabel")}
                      value={link.label}
                      onChange={(v) => patchLink(i, { label: v })}
                      maxLength={120}
                      placeholder="Portfolio"
                      testId={`link-label-${i}`}
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      patch({ links: links.filter((_, j) => j !== i) })
                    }
                    className="cursor-pointer rounded-md p-1 text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-danger)]"
                    aria-label={t("profileSection.removeLink")}
                    data-testid={`link-remove-${i}`}
                  >
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </div>
              </FormRow>
            ))}
            {links.length < MAX_LINKS && (
              <button
                type="button"
                onClick={() =>
                  patch({
                    links: [
                      ...links,
                      { kind: "other", url: "", label: "" },
                    ],
                  })
                }
                className="cursor-pointer rounded-lg border border-dashed border-[var(--as-border)] px-3 py-1.5 text-xs text-[var(--as-muted-fg)] transition-colors hover:border-[var(--as-accent)] hover:text-[var(--as-fg)]"
                data-testid="add-link"
              >
                {t("profileSection.addLink")}
              </button>
            )}
          </div>
          <div data-testid="basics-birth-year">
            <OptionalStepper
              label={t("profileSection.birthYear")}
              value={draft.birth_year}
              min={BIRTH_MIN}
              max={BIRTH_MAX}
              onChange={(v) => patch({ birth_year: v })}
              addValue={CURRENT_YEAR - 20}
              addLabel={t("experience.hoursSet")}
            />
          </div>
          <SelectField
            label={t("profileSection.educationLevel")}
            value={draft.education_level}
            options={EDUCATION_OPTIONS.map((o) => ({
              value: o.value,
              label: t(o.labelKey, { defaultValue: o.label }),
            }))}
            testId="basics-education-level"
            onChange={(v) =>
              patch({ education_level: v as Profile["basics"]["education_level"] })
            }
          />
          {gradeFields && (
            <TextField
              label={t("profileSection.grade")}
              value={draft.grade ?? ""}
              onChange={(v) => patch({ grade: v || null })}
              maxLength={30}
              placeholder={t("profileSection.gradePlaceholder")}
              testId="basics-grade"
            />
          )}
        </div>
      </ProfileSectionCard>
    );
  }
);
