import {
  ComboboxMultiField,
  DateField,
  FormRow,
  OptionalStepper,
  SegmentedRow,
  TextField,
  TextareaField,
  ToggleRow,
} from "@/components/cv/formPrimitives";
import { Button, EmptyState } from "@/components/ui";
import type {
  AchievementIn,
  ExperienceItemIn,
  ExperienceItemOut,
  ExperienceSkillIn,
} from "@/types/experience";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import i18next from "i18next";
import { Plus, X } from "lucide-react";
import { slugifyKey } from "@/lib/slug";

export const KINDS: {
  value: ExperienceItemIn["kind"];
  labelKey: string;
}[] = [
  { value: "job", labelKey: "experience.kind.job" },
  { value: "internship", labelKey: "experience.kind.internship" },
  { value: "project", labelKey: "experience.kind.project" },
  { value: "freelance", labelKey: "experience.kind.freelance" },
  { value: "volunteer", labelKey: "experience.kind.volunteer" },
];

const ONSITE_POLICIES = [
  { value: "onsite", labelKey: "experience.onsite.onsite" },
  { value: "hybrid", labelKey: "experience.onsite.hybrid" },
  { value: "remote", labelKey: "experience.onsite.remote" },
];

const STATUS_OPTIONS = [
  { value: "active", labelKey: "experience.statusOption.active" },
  { value: "draft", labelKey: "experience.statusOption.draft" },
];

const ROLE_OPTIONS = [
  { value: "primary", labelKey: "experience.role.primary" },
  { value: "secondary", labelKey: "experience.role.secondary" },
  { value: "exposure", labelKey: "experience.role.exposure" },
];

export interface ExperienceEditorForm {
  title: string;
  kind: ExperienceItemIn["kind"];
  org_name: string;
  start: string;
  end: string;
  open_ended: boolean;
  hours_per_week: number | null;
  onsite_policy: Exclude<ExperienceItemIn["onsite_policy"], null>;
  description: string;
  status: "draft" | "active";
  skills: ExperienceSkillIn[];
  achievements: AchievementIn[];
}

export const EMPTY_FORM: ExperienceEditorForm = {
  title: "",
  kind: "project",
  org_name: "",
  start: "",
  end: "",
  open_ended: false,
  hours_per_week: null,
  onsite_policy: "onsite",
  description: "",
  status: "active",
  skills: [],
  achievements: [],
};

export function formFromItem(item: ExperienceItemOut): ExperienceEditorForm {
  return {
    title: item.title,
    kind: item.kind,
    org_name: item.org_name,
    start: item.start,
    end: item.end ?? "",
    open_ended: item.open_ended,
    hours_per_week: item.hours_per_week,
    onsite_policy: (item.onsite_policy ?? "onsite") as Exclude<
      ExperienceItemIn["onsite_policy"],
      null
    >,
    description: item.description,
    status: item.status,
    skills: item.skills.map((s) => ({
      skill_key: s.skill_key,
      role_in_item: s.role_in_item,
      level_claim: s.level_claim,
      last_used: s.last_used,
    })),
    achievements: item.achievements.map((a) => ({ text: a.text, metric: null })),
  };
}

export function validateExperience(form: ExperienceEditorForm): {
  title?: string;
  start?: string;
  end?: string;
  hours?: string;
  achievements: string[];
} {
  const errors: ReturnType<typeof validateExperience> = { achievements: [] };
  const title = form.title.trim()
    ? null
    : i18next.t("validation.required", {
        field: i18next.t("experience.field.title"),
      });
  if (title) errors.title = title;
  const start = form.start.trim()
    ? null
    : i18next.t("validation.required", {
        field: i18next.t("experience.field.start"),
      });
  if (start) errors.start = start;
  if (!form.open_ended && form.start && !form.end) {
    errors.end = i18next.t("experience.validation.endRequired");
  } else if (!form.open_ended && form.start && form.end && form.end < form.start) {
    errors.end = i18next.t("experience.validation.endBeforeStart");
  }
  const hours =
    form.hours_per_week === null
      ? null
      : Number.isNaN(form.hours_per_week) ||
          form.hours_per_week < 1 ||
          form.hours_per_week > 80
        ? i18next.t("validation.range", {
            field: i18next.t("experience.field.hours"),
            min: 1,
            max: 80,
          })
        : null;
  if (hours) errors.hours = hours;
  form.achievements.forEach((a, i) => {
    if (!a.text.trim())
      errors.achievements[i] = i18next.t(
        "experience.validation.achievementRequired"
      );
  });
  return errors;
}

export function ExperienceEditor({
  form,
  onChange,
  onSave,
  onCancel,
  onDismissErrors,
  showErrors,
  skillOptions,
  saving,
  isNew,
}: {
  form: ExperienceEditorForm;
  onChange: (patch: Partial<ExperienceEditorForm>) => void;
  onSave: () => void;
  onCancel: () => void;
  onDismissErrors: () => void;
  showErrors: boolean;
  skillOptions: { value: string; label: string }[];
  saving: boolean;
  isNew: boolean;
}) {
  const { t } = useTranslation();
  const errors = validateExperience(form);
  const patch = (partial: Partial<ExperienceEditorForm>) => {
    onDismissErrors();
    onChange(partial);
  };
  const err = (message?: string) => (showErrors && message ? message : undefined);

  const [createdSkills, setCreatedSkills] = useState<
    { key: string; label: string }[]
  >([]);
  const skillChoices = useMemo(() => {
    const known = new Set(skillOptions.map((o) => o.value));
    return [
      ...skillOptions,
      ...createdSkills.filter((c) => !known.has(c.key)).map((c) => ({ value: c.key, label: c.label })),
    ];
  }, [skillOptions, createdSkills]);

  const setSkills = (values: string[]) => {
    const created: { key: string; label: string }[] = [];
    const keys = values.map((value) => {
      const existing = skillOptions.find((o) => o.value === value);
      if (existing || createdSkills.some((c) => c.key === value)) return value;
      const key = slugifyKey(value);
      if (key) created.push({ key, label: value });
      return key || value;
    });
    if (created.length > 0) setCreatedSkills((prev) => [...prev, ...created]);
    patch({
      skills: keys.map((key) => {
        const prior =
          form.skills.find((s) => s.skill_key === key) ??
          form.skills.find((s) => s.skill_key === values[keys.indexOf(key)]);
        return (
          prior ?? {
            skill_key: key,
            role_in_item: "primary" as const,
            level_claim: null,
            last_used: null,
          }
        );
      }),
    });
  };

  return (
    <div
      className="flex min-h-0 flex-1 flex-col overflow-y-auto"
      data-testid="experience-editor"
    >
      <div className="sticky top-0 z-10 flex shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-[var(--as-border)] bg-[var(--as-surface)] px-5 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-[var(--as-fg)]">
            {isNew ? t("experience.addTitle") : t("experience.editTitle")}
          </h2>
          <p className="mt-0.5 truncate text-xs text-[var(--as-muted-fg)]">
            {t("experience.editorHint")}
          </p>
        </div>
        <SegmentedRow
          label={t("experience.statusLabel")}
          value={form.status}
          options={STATUS_OPTIONS.map((o) => ({
            value: o.value,
            label: t(o.labelKey),
          }))}
          onChange={(v) => patch({ status: v as "draft" | "active" })}
        />
      </div>

      <div className="mx-auto w-full max-w-2xl space-y-4 px-5 py-4">
        <SegmentedRow
          label={t("experience.kindLabel")}
          value={form.kind}
          options={KINDS.map((o) => ({ value: o.value, label: t(o.labelKey) }))}
          onChange={(v) => patch({ kind: v as ExperienceItemIn["kind"] })}
        />
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField
            label={t("experience.roleTitleLabel")}
            value={form.title}
            onChange={(v) => patch({ title: v })}
            maxLength={160}
            placeholder={t("experience.roleTitlePlaceholder")}
            error={err(errors.title)}
            testId="experience-title"
          />
          <TextField
            label={t("experience.orgLabel")}
            value={form.org_name}
            onChange={(v) => patch({ org_name: v })}
            maxLength={200}
            placeholder={t("experience.orgPlaceholder")}
            testId="experience-org"
          />
        </div>
        <div className="grid items-end gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
          <DateField
            label={t("experience.field.start")}
            value={form.start || null}
            onChange={(v) => patch({ start: v })}
            error={err(errors.start)}
            testId="experience-start"
          />
          <DateField
            label={t("experience.endLabel")}
            value={form.end || null}
            onChange={(v) => patch({ end: v })}
            disabled={form.open_ended}
            hint={form.open_ended ? t("experience.ongoingHint") : undefined}
            error={err(errors.end)}
            testId="experience-end"
          />
          <div className="pb-2">
            <ToggleRow
              label={t("experience.ongoingToggle")}
              checked={form.open_ended}
              onChange={(checked) =>
                patch({ open_ended: checked, end: checked ? "" : form.end })
              }
            />
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="min-w-0" data-testid="experience-hours">
            <OptionalStepper
              label={t("experience.field.hours")}
              value={form.hours_per_week}
              min={1}
              max={80}
              onChange={(v) => patch({ hours_per_week: v })}
              addValue={20}
              addLabel={t("experience.hoursSet")}
              suffix="1–80"
            />
            <FormRow error={err(errors.hours)} />
          </div>
          <SegmentedRow
            label={t("experience.onsiteLabel")}
            value={form.onsite_policy}
            options={ONSITE_POLICIES.map((o) => ({
              value: o.value,
              label: t(o.labelKey),
            }))}
            onChange={(v) =>
              patch({ onsite_policy: v as Exclude<ExperienceItemIn["onsite_policy"], null> })
            }
          />
        </div>
        <TextareaField
          label={t("experience.descriptionLabel")}
          value={form.description}
          onChange={(v) => patch({ description: v })}
          rows={4}
          maxLength={2000}
          counter
          placeholder={t("experience.descriptionPlaceholder")}
          testId="experience-description"
        />

        <div className="space-y-2">
          <ComboboxMultiField
            label={t("experience.skillsLabel")}
            values={form.skills.map((s) => s.skill_key)}
            onChange={setSkills}
            options={skillChoices}
            maxTriggerLabels={5}
            allowCreate
            createLabel={(term) => t("experience.addSkill", { name: term })}
            hint={t("experience.skillsHint")}
            testId="experience-skills"
          />
          {form.skills.length > 0 && (
            <div className="space-y-1.5 rounded-lg border border-[var(--as-border)] p-2.5">
              {form.skills.map((s, i) => (
                <div
                  key={s.skill_key}
                  className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2"
                >
                  <span className="truncate text-xs text-[var(--as-fg)]">
                    {skillChoices.find((o) => o.value === s.skill_key)?.label ?? s.skill_key}
                  </span>
                  <select
                    className="w-28 cursor-pointer rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] p-1 text-xs outline-none transition-colors focus:border-[var(--as-accent)]"
                    value={s.role_in_item}
                    aria-label={t("experience.roleForAria", { skill: s.skill_key })}
                    onChange={(e) =>
                      patch({
                        skills: form.skills.map((x, j) =>
                          j === i
                            ? { ...x, role_in_item: e.target.value as ExperienceSkillIn["role_in_item"] }
                            : x
                        ),
                      })
                    }
                    data-testid={`skill-role-${i}`}
                  >
                    {ROLE_OPTIONS.map((r) => (
                      <option key={r.value} value={r.value}>
                        {t(r.labelKey)}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() =>
                      patch({ skills: form.skills.filter((_, j) => j !== i) })
                    }
                    className="cursor-pointer rounded-md p-1 text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-danger)]"
                    aria-label={t("experience.removeSkillAria", { skill: s.skill_key })}
                    data-testid={`skill-remove-${i}`}
                  >
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="space-y-2">
          <p className="text-xs text-[var(--as-muted-fg)]">
            {t("experience.achievementsLabel")}
          </p>
          {form.achievements.map((a, i) => (
            <FormRow key={i} error={err(errors.achievements[i])}>
              <div className="flex items-end gap-2">
                <div className="min-w-0 flex-1">
                  <TextField
                    label={t("experience.achievementN", { index: i + 1 })}
                    value={a.text}
                    onChange={(text) =>
                      patch({
                        achievements: form.achievements.map((x, j) =>
                          j === i ? { ...x, text } : x
                        ),
                      })
                    }
                    maxLength={500}
                    placeholder={t("experience.achievementPlaceholder")}
                    testId={`achievement-text-${i}`}
                  />
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => patch({ achievements: form.achievements.filter((_, j) => j !== i) })}
                  aria-label={t("experience.removeAchievementN", { index: i + 1 })}
                  title={t("experience.removeAchievement")}
                  data-testid={`achievement-remove-${i}`}
                >
                  <X className="h-3.5 w-3.5" aria-hidden />
                </Button>
              </div>
            </FormRow>
          ))}
          <button
            type="button"
            onClick={() => patch({ achievements: [...form.achievements, { text: "", metric: null }] })}
            className="cursor-pointer rounded-lg border border-dashed border-[var(--as-border)] px-3 py-1.5 text-xs text-[var(--as-muted-fg)] transition-colors hover:border-[var(--as-accent)] hover:text-[var(--as-fg)]"
            data-testid="add-achievement"
          >
            <Plus className="mr-1 inline h-3.5 w-3.5" aria-hidden />
            {t("experience.addAchievement")}
          </button>
        </div>
      </div>

      <div className="sticky bottom-0 mt-auto flex shrink-0 items-center justify-end gap-2 border-t border-[var(--as-border)] bg-[var(--as-surface)] px-5 py-3">
        <Button variant="ghost" onClick={onCancel} data-testid="cancel-experience">
          {t("common.cancel")}
        </Button>
        <Button variant="default" onClick={onSave} disabled={saving} data-testid="save-experience">
          {saving ? t("common.saving") : t("common.save")}
        </Button>
      </div>
    </div>
  );
}

export function ExperienceEditorEmpty({ onAdd }: { onAdd: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center p-6" data-testid="experience-editor">
      <EmptyState
        title={t("experience.nothingSelected")}
        description={t("experience.emptyBody")}
        action={
          <Button variant="default" onClick={onAdd}>
            {t("experience.addEntry")}
          </Button>
        }
      />
    </div>
  );
}
