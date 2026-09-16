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
import { CvRichTextEditor } from "@/components/cv/CvRichTextEditor";
import { Button } from "@/components/ui";
import type {
  AchievementIn,
  ExperienceItemIn,
  ExperienceItemOut,
  ExperienceLinkIn,
  ExperienceSkillIn,
} from "@/types/experience";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import i18next from "i18next";
import {
  Briefcase,
  ChevronDown,
  ChevronUp,
  Coins,
  GraduationCap,
  Hammer,
  HeartHandshake,
  Plus,
  X,
} from "lucide-react";
import { slugifyKey } from "@/lib/slug";

export const KIND_ICONS: Record<ExperienceItemIn["kind"], typeof Briefcase> = {
  job: Briefcase,
  internship: GraduationCap,
  project: Hammer,
  freelance: Coins,
  volunteer: HeartHandshake,
};

const METRIC_KINDS = [
  { value: "time_saved", labelKey: "experience.metricKind.time_saved" },
  { value: "scale", labelKey: "experience.metricKind.scale" },
  { value: "revenue", labelKey: "experience.metricKind.revenue" },
  { value: "quality", labelKey: "experience.metricKind.quality" },
] as const;

function reorder<T>(list: T[], from: number, to: number): T[] {
  if (to < 0 || to >= list.length) return list;
  const next = [...list];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}


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
  links: ExperienceLinkIn[];
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
  links: [],
  skills: [],
  achievements: [],
};

export function formFromItem(item: ExperienceItemOut): ExperienceEditorForm {
  return {
    title: item.title,
    kind: item.kind,
    org_name: item.org_name,
    start: item.start ?? "",
    end: item.end ?? "",
    open_ended: item.open_ended,
    hours_per_week: item.hours_per_week,
    onsite_policy: (item.onsite_policy ?? "onsite") as Exclude<
      ExperienceItemIn["onsite_policy"],
      null
    >,
    description: item.description,
    status: item.status,
    links: item.links
      .filter((l) => typeof l.url === "string" && l.url)
      .map((l) => ({
        label: typeof l.label === "string" ? l.label : "",
        url: l.url as string,
        kind: (
          ["github", "linkedin", "demo", "web"].includes(String(l.kind))
            ? String(l.kind)
            : "web"
        ) as ExperienceLinkIn["kind"],
      })),
    skills: item.skills.map((s) => ({
      skill_key: s.skill_key,
      role_in_item: s.role_in_item,
      level_claim: s.level_claim,
      last_used: s.last_used,
    })),
    achievements: item.achievements.map((a) => ({
      text: a.text,
      metric: a.metric ? { ...a.metric } : null,
    })),
  };
}

export function validateExperience(form: ExperienceEditorForm): {
  title?: string;
  start?: string;
  end?: string;
  hours?: string;
  links: string[];
  achievements: string[];
} {
  const errors: ReturnType<typeof validateExperience> = {
    achievements: [],
    links: [],
  };
  const title = form.title.trim()
    ? null
    : i18next.t("validation.required", {
        field: i18next.t("experience.field.title"),
      });
  if (title) errors.title = title;
  const start =
    form.kind === "project" || form.start.trim()
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
  form.links.forEach((l, i) => {
    if (!/^https?:\/\//i.test(l.url.trim())) {
      errors.links[i] = i18next.t("experience.validation.linkUrl");
    }
  });
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

      <div className="mx-auto w-full max-w-4xl space-y-6 px-5 py-5">
        <div className="flex flex-wrap gap-1.5" aria-label={t("experience.kindLabel")}>
          {KINDS.map((o) => {
            const KindIcon = KIND_ICONS[o.value];
            const selected = form.kind === o.value;
            return (
              <button
                key={o.value}
                type="button"
                aria-pressed={selected}
                onClick={() => patch({ kind: o.value as ExperienceItemIn["kind"] })}
                className={`flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors duration-150 ${
                  selected
                    ? "border-[var(--as-accent)] bg-[var(--as-accent)] text-white shadow-sm"
                    : "border-[var(--as-border)] bg-[var(--as-surface)] text-[var(--as-muted-fg)] hover:border-[var(--as-accent)] hover:text-[var(--as-fg)]"
                }`}
              >
                <KindIcon className="h-3.5 w-3.5" aria-hidden />
                {t(o.labelKey)}
              </button>
            );
          })}
        </div>

        <div className="space-y-1.5">
          <input
            value={form.title}
            onChange={(e) => patch({ title: e.target.value })}
            maxLength={160}
            placeholder={t("experience.roleTitlePlaceholder")}
            aria-label={t("experience.roleTitleLabel")}
            data-testid="experience-title"
            className="w-full cursor-text rounded-lg border border-transparent bg-transparent px-2 py-1 text-xl font-semibold text-[var(--as-fg)] outline-none transition-colors duration-150 placeholder:text-[var(--as-muted-fg)]/50 hover:border-[var(--as-border)] focus:border-[var(--as-accent)] focus:bg-[var(--as-surface)]"
          />
          {err(errors.title) && (
            <p className="px-2 text-xs text-[var(--as-danger)]">{err(errors.title)}</p>
          )}
          <input
            value={form.org_name}
            onChange={(e) => patch({ org_name: e.target.value })}
            maxLength={200}
            placeholder={t("experience.orgLabel")}
            aria-label={t("experience.orgLabel")}
            data-testid="experience-org"
            className="w-full cursor-text rounded-lg border border-transparent bg-transparent px-2 py-1 text-sm text-[var(--as-fg)] outline-none transition-colors duration-150 placeholder:text-[var(--as-muted-fg)]/70 hover:border-[var(--as-border)] focus:border-[var(--as-accent)] focus:bg-[var(--as-surface)]"
          />
        </div>

        <section
          className="space-y-3 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface-raised)]/40 p-3.5"
          data-testid="experience-period"
        >
          <div className="grid items-start gap-x-4 gap-y-3 sm:grid-cols-2">
            <div className="space-y-3">
              <ToggleRow
                label={t("experience.ongoingToggle")}
                checked={form.open_ended}
                onChange={(checked) =>
                  patch({ open_ended: checked, end: checked ? "" : form.end })
                }
              />
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
            </div>
            <div className="space-y-3 sm:border-l sm:border-[var(--as-border)] sm:pl-4">
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
          </div>
        </section>

        <div className="ca-editor-cols grid items-start gap-6">
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
              {t("experience.descriptionLabel")}
            </p>
            <CvRichTextEditor
              value={form.description}
              onChange={(v) => patch({ description: v })}
              ariaLabel={t("experience.descriptionLabel")}
              testId="experience-description"
            />
          </div>
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
              {t("experience.achievementsLabel")}
            </p>
            {form.achievements.map((a, i) => (
              <FormRow key={i} error={err(errors.achievements[i])}>
                <div
                  className="space-y-1.5 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] p-2.5 transition-colors duration-150 hover:border-[var(--as-accent)]"
                  data-testid={`achievement-${i}`}
                >
                  <TextareaField
                    label={t("experience.achievementN", { index: i + 1 })}
                    value={a.text}
                    onChange={(text) =>
                      patch({
                        achievements: form.achievements.map((x, j) =>
                          j === i ? { ...x, text } : x
                        ),
                      })
                    }
                    rows={2}
                    maxLength={500}
                    placeholder={t("experience.achievementPlaceholder")}
                    testId={`achievement-text-${i}`}
                  />
                  {a.metric ? (
                    <div className="flex flex-wrap items-center gap-1.5">
                      <select
                        className="cursor-pointer rounded-full border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-xs text-[var(--as-fg)] outline-none transition-colors focus:border-[var(--as-accent)]"
                        value={a.metric.kind}
                        aria-label={t("experience.metricKindLabel")}
                        onChange={(e) =>
                          patch({
                            achievements: form.achievements.map((x, j) =>
                              j === i
                                ? { ...x, metric: { ...x.metric!, kind: e.target.value } }
                                : x
                            ),
                          })
                        }
                        data-testid={`achievement-metric-kind-${i}`}
                      >
                        {METRIC_KINDS.map((m) => (
                          <option key={m.value} value={m.value}>
                            {t(m.labelKey)}
                          </option>
                        ))}
                      </select>
                      <input
                        type="number"
                        value={a.metric.value}
                        aria-label={t("experience.metricValueLabel")}
                        onChange={(e) =>
                          patch({
                            achievements: form.achievements.map((x, j) =>
                              j === i
                                ? { ...x, metric: { ...x.metric!, value: Number(e.target.value) } }
                                : x
                            ),
                          })
                        }
                        className="w-20 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-xs tabular-nums outline-none transition-colors focus:border-[var(--as-accent)]"
                        data-testid={`achievement-metric-value-${i}`}
                      />
                      <input
                        value={a.metric.unit}
                        aria-label={t("experience.metricUnitLabel")}
                        placeholder="%"
                        maxLength={12}
                        onChange={(e) =>
                          patch({
                            achievements: form.achievements.map((x, j) =>
                              j === i
                                ? { ...x, metric: { ...x.metric!, unit: e.target.value } }
                                : x
                            ),
                          })
                        }
                        className="w-16 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-xs outline-none transition-colors focus:border-[var(--as-accent)]"
                        data-testid={`achievement-metric-unit-${i}`}
                      />
                      <button
                        type="button"
                        onClick={() =>
                          patch({
                            achievements: form.achievements.map((x, j) =>
                              j === i ? { ...x, metric: null } : x
                            ),
                          })
                        }
                        className="cursor-pointer rounded-md p-1 text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-danger)]"
                        aria-label={t("experience.metricRemove")}
                        data-testid={`achievement-metric-remove-${i}`}
                      >
                        <X className="h-3.5 w-3.5" aria-hidden />
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() =>
                        patch({
                          achievements: form.achievements.map((x, j) =>
                            j === i
                              ? { ...x, metric: { kind: "time_saved", value: 10, unit: "%" } }
                              : x
                          ),
                        })
                      }
                      className="cursor-pointer rounded-md border border-dashed border-[var(--as-border)] px-2 py-0.5 text-[11px] text-[var(--as-muted-fg)] transition-colors hover:border-[var(--as-accent)] hover:text-[var(--as-fg)]"
                      data-testid={`achievement-metric-add-${i}`}
                    >
                      <Plus className="mr-1 inline h-3 w-3" aria-hidden />
                      {t("experience.metricAdd")}
                    </button>
                  )}
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      disabled={i === 0}
                      onClick={() =>
                        patch({
                          achievements: reorder(form.achievements, i, i - 1),
                        })
                      }
                      className="cursor-pointer rounded-md p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] disabled:pointer-events-none disabled:opacity-40"
                      aria-label={t("experience.bulletUp")}
                      data-testid={`achievement-up-${i}`}
                    >
                      <ChevronUp className="h-3.5 w-3.5" aria-hidden />
                    </button>
                    <button
                      type="button"
                      disabled={i === form.achievements.length - 1}
                      onClick={() =>
                        patch({
                          achievements: reorder(form.achievements, i, i + 1),
                        })
                      }
                      className="cursor-pointer rounded-md p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] disabled:pointer-events-none disabled:opacity-40"
                      aria-label={t("experience.bulletDown")}
                      data-testid={`achievement-down-${i}`}
                    >
                      <ChevronDown className="h-3.5 w-3.5" aria-hidden />
                    </button>
                    <span className="flex-1" />
                    <button
                      type="button"
                      onClick={() => patch({ achievements: form.achievements.filter((_, j) => j !== i) })}
                      className="cursor-pointer rounded-md p-1 text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-danger)]"
                      aria-label={t("experience.removeAchievementN", { index: i + 1 })}
                      title={t("experience.removeAchievement")}
                      data-testid={`achievement-remove-${i}`}
                    >
                      <X className="h-3.5 w-3.5" aria-hidden />
                    </button>
                  </div>
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
            <div className="space-y-1.5">
              {form.skills.map((s, i) => (
                <div
                  key={s.skill_key}
                  className="flex items-center gap-2 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2.5 py-1.5 transition-colors duration-150 hover:border-[var(--as-accent)]"
                >
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-[var(--as-fg)]">
                    {skillChoices.find((o) => o.value === s.skill_key)?.label ?? s.skill_key}
                  </span>
                  <select
                    className="cursor-pointer rounded-full border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-xs text-[var(--as-fg)] outline-none transition-colors focus:border-[var(--as-accent)]"
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
                  <OptionalStepper
                    compact
                    label={skillChoices.find((o) => o.value === s.skill_key)?.label ?? s.skill_key}
                    value={s.level_claim}
                    min={1}
                    max={10}
                    onChange={(level_claim) =>
                      patch({
                        skills: form.skills.map((x, j) =>
                          j === i ? { ...x, level_claim } : x
                        ),
                      })
                    }
                    addValue={5}
                    addLabel={t("experience.setLevelClaim")}
                    decreaseAria={t("experience.claimDecreaseAria")}
                    increaseAria={t("experience.claimIncreaseAria")}
                    clearAria={t("experience.claimClearAria")}
                    clearTitle={t("experience.claimClear")}
                    testIdPrefix={`skill-claim-${i}`}
                  />
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
          <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
            {t("experience.linksLabel")}
          </p>
          {form.links.map((l, i) => (
            <FormRow key={i} error={err(errors.links[i])}>
              <div className="flex items-end gap-2">
                <div className="w-36 shrink-0">
                  <select
                    className="w-full cursor-pointer rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-xs outline-none transition-colors focus:border-[var(--as-accent)]"
                    value={l.kind}
                    aria-label={t("experience.linkKindAria", { index: i + 1 })}
                    onChange={(e) =>
                      patch({
                        links: form.links.map((x, j) =>
                          j === i
                            ? { ...x, kind: e.target.value as ExperienceLinkIn["kind"] }
                            : x
                        ),
                      })
                    }
                    data-testid={`link-kind-${i}`}
                  >
                    {(["github", "linkedin", "demo", "web"] as const).map((k) => (
                      <option key={k} value={k}>
                        {t(`experience.linkKind.${k}`)}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="min-w-0 flex-1">
                  <TextField
                    label={t("experience.linkN", { index: i + 1 })}
                    value={l.url}
                    onChange={(url) =>
                      patch({
                        links: form.links.map((x, j) => (j === i ? { ...x, url } : x)),
                      })
                    }
                    maxLength={500}
                    placeholder={t("experience.linkPlaceholder")}
                    testId={`link-url-${i}`}
                  />
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => patch({ links: form.links.filter((_, j) => j !== i) })}
                  aria-label={t("experience.removeLinkN", { index: i + 1 })}
                  title={t("experience.removeLink")}
                  data-testid={`link-remove-${i}`}
                >
                  <X className="h-3.5 w-3.5" aria-hidden />
                </Button>
              </div>
            </FormRow>
          ))}
          {form.links.length < 10 && (
            <button
              type="button"
              onClick={() =>
                patch({
                  links: [...form.links, { label: "", url: "", kind: "web" }],
                })
              }
              className="cursor-pointer rounded-lg border border-dashed border-[var(--as-border)] px-3 py-1.5 text-xs text-[var(--as-muted-fg)] transition-colors hover:border-[var(--as-accent)] hover:text-[var(--as-fg)]"
              data-testid="add-link"
            >
              <Plus className="mr-1 inline h-3.5 w-3.5" aria-hidden />
              {t("experience.addLink")}
            </button>
          )}
        </div>
      </div>

      <div className="sticky bottom-0 mt-auto flex shrink-0 items-center justify-end gap-2 border-t border-[var(--as-border)] bg-[var(--as-surface)] py-3 pl-5 pr-24 sm:pl-10">
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

