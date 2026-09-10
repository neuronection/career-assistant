import { forwardRef } from "react";
import { useTranslation } from "react-i18next";
import {
  ChipTogglesRow,
  OptionalStepper,
  SelectField,
  ToggleRow,
} from "@/components/cv/formPrimitives";
import { ProfileSectionCard } from "@/components/profile/ProfileSectionCard";
import type { Profile } from "@/types";
import { CONDITION_OPTIONS } from "./options";
import {
  useSectionCard,
  type SectionCardBaseProps,
  type SectionCardHandle,
} from "./shared";

export interface ConstraintsCardProps
  extends SectionCardBaseProps<Profile["constraints"]> {}

export const ConstraintsCard = forwardRef<
  SectionCardHandle,
  ConstraintsCardProps
>(function ConstraintsCard(
  { initial, onSave, mode = "autosave", variant = "page", complete = null },
  ref
) {
  const { t } = useTranslation();
  const { draft, setDraft, state, error } = useSectionCard(ref, {
    initial,
    onSave,
    mode,
    buildPayload: (d) => ({ constraints: d }),
  });
  const patch = (partial: Partial<Profile["constraints"]>) =>
    setDraft({ ...draft, ...partial });

  return (
    <ProfileSectionCard
      name="constraints"
      title={t("profileSection.constraints")}
      description={
        variant === "page"
          ? t("profileSection.constraintsBody")
          : undefined
      }
      complete={complete}
      saveState={state}
      error={error}
      variant={variant}
    >
      <div className="space-y-4">
        <ChipTogglesRow
          label={t("profileSection.conditions")}
          values={draft.physical_conditions}
          options={CONDITION_OPTIONS.map((o) => ({
            value: o.value,
            label: t(o.labelKey, { defaultValue: o.label }),
          }))}
          onChange={(values) => patch({ physical_conditions: values })}
        />
        <div data-testid="constraints-education-years">
          <OptionalStepper
            label={t("profileSection.maxEducationYears")}
            value={draft.max_education_years}
            min={0}
            max={12}
            onChange={(v) => patch({ max_education_years: v })}
            addValue={4}
            addLabel="Set"
            suffix="0–12"
          />
        </div>
        <div data-testid="constraints-hours">
          <OptionalStepper
            label={t("experience.field.hours")}
            value={draft.hours_available_per_week}
            min={1}
            max={80}
            onChange={(v) => patch({ hours_available_per_week: v })}
            addValue={20}
            addLabel="Set"
            suffix="1–80"
          />
        </div>
        <ToggleRow
          label={t("profileSection.relocate")}
          checked={draft.willing_to_relocate}
          onChange={(checked) => patch({ willing_to_relocate: checked })}
        />
        <div data-testid="constraints-salary-min">
          <OptionalStepper
            label={t("profileSection.salaryMin")}
            value={draft.salary_min}
            min={0}
            max={20000}
            step={100}
            onChange={(v) => patch({ salary_min: v })}
            addValue={800}
            addLabel="Set"
            suffix="€, 0–20k"
          />
        </div>
        <ToggleRow
          label={t("profileSection.salaryNegotiable")}
          checked={draft.salary_negotiable}
          onChange={(checked) => patch({ salary_negotiable: checked })}
        />
        <div data-testid="constraints-travel">
          <OptionalStepper
            label={t("profileSection.travelDays")}
            value={draft.travel_days_per_month}
            min={0}
            max={30}
            onChange={(v) => patch({ travel_days_per_month: v })}
            addValue={5}
            addLabel="Set"
            suffix="0–30"
          />
        </div>
        <div data-testid="constraints-shift-tolerance">
          <SelectField
            label={t("profileSection.shiftTolerance")}
            value={draft.shift_tolerance ?? ""}
            onChange={(value) =>
              patch({
                shift_tolerance:
                  value === "" ? null : (value as "none" | "occasional" | "regular"),
              })
            }
            options={[
              { value: "", label: "No preference recorded" },
              { value: "none", label: "No shifts or on-call" },
              { value: "occasional", label: "Occasional shifts are fine" },
              { value: "regular", label: "Regular shifts are fine" },
            ]}
            testId="shift-tolerance-select"
          />
        </div>
        <div data-testid="constraints-commute">
          <OptionalStepper
            label={t("profileSection.commuteRadius")}
            value={draft.commute_radius_km}
            min={0}
            max={500}
            step={10}
            onChange={(v) => patch({ commute_radius_km: v })}
            addValue={25}
            addLabel="Set"
            suffix="km, 0–500"
          />
        </div>
      </div>
    </ProfileSectionCard>
  );
});
