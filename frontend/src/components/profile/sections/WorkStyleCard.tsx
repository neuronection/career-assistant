import { forwardRef } from "react";
import { useTranslation } from "react-i18next";
import { BarChart3, Lightbulb, Users, Wrench } from "lucide-react";
import {
  RangeField,
  SegmentedRow,
  ToggleRow,
} from "@/components/cv/formPrimitives";
import { ProfileSectionCard } from "@/components/profile/ProfileSectionCard";
import type { Profile } from "@/types";
import { FOCUS_AREAS, PHYSICAL_ACTIVITY_OPTIONS, WORK_SCALES } from "./options";
import {
  useSectionCard,
  type SectionCardBaseProps,
  type SectionCardHandle,
} from "./shared";

export interface WorkStyleCardProps
  extends SectionCardBaseProps<Profile["work_preferences"]> {}

const FOCUS_ICONS = { people: Users, things: Wrench, data: BarChart3, ideas: Lightbulb };

export const WorkStyleCard = forwardRef<SectionCardHandle, WorkStyleCardProps>(
  function WorkStyleCard(
    { initial, onSave, mode = "autosave", variant = "page", complete = null },
    ref
  ) {
    const { t } = useTranslation();
    const { draft, setDraft, state, error } = useSectionCard(ref, {
      initial,
      onSave,
      mode,
      buildPayload: (d) => ({ work_preferences: d }),
    });
    const patch = (partial: Partial<Profile["work_preferences"]>) =>
      setDraft({ ...draft, ...partial });

    return (
      <ProfileSectionCard
        name="work-style"
        title={t("profileSection.workStyle")}
        description={
          variant === "page"
            ? t("profileSection.workStyleBody")
            : undefined
        }
        complete={complete}
        saveState={state}
        error={error}
        variant={variant}
      >
        <div className="space-y-6">
          <div className="grid gap-x-8 gap-y-5 sm:grid-cols-2">
            {WORK_SCALES.map(({ key, labelKey, lowKey, highKey, label, low, high }) => (
              <div key={key} data-testid={`workstyle-${key}`}>
                <RangeField
                  label={t(labelKey, { defaultValue: label })}
                  value={draft[key] as number}
                  min={1}
                  max={5}
                  onChange={(v) => patch({ [key]: v } as Partial<Profile["work_preferences"]>)}
                />
                <div className="flex justify-between text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)]">
                  <span>{t(lowKey, { defaultValue: low })}</span>
                  <span>{t(highKey, { defaultValue: high })}</span>
                </div>
              </div>
            ))}
          </div>

          <div className="max-w-xs">
            <ToggleRow
              label={t("profileSection.remoteOk")}
              checked={draft.remote_ok}
              onChange={(checked) => patch({ remote_ok: checked })}
            />
          </div>

          <SegmentedRow
            label={t("profileSection.physicalActivity")}
            value={draft.physical_activity}
            options={PHYSICAL_ACTIVITY_OPTIONS.map((o) => ({
              value: o.value,
              label: t(o.labelKey, { defaultValue: o.label }),
            }))}
            onChange={(v) =>
              patch({ physical_activity: v as Profile["work_preferences"]["physical_activity"] })
            }
          />

          <div>
            <h3 className="text-xs font-semibold text-[var(--as-fg)]">
              {t("profileSection.focusHeading")}
            </h3>
            <p className="mb-2 mt-0.5 text-xs text-[var(--as-muted-fg)]">
              {t("profileSection.focusBody")}
            </p>
            <div className="grid gap-2 sm:grid-cols-2" data-testid="focus-areas">
              {FOCUS_AREAS.map(({ key, labelKey, label, hint }) => {
                const Icon = FOCUS_ICONS[key];
                const active = draft.focus_areas.includes(key);
                return (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={active}
                    onClick={() => {
                      const next = active
                        ? draft.focus_areas.filter((a) => a !== key)
                        : [...draft.focus_areas, key];
                      patch({ focus_areas: next });
                    }}
                    className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 text-left transition-colors duration-150 ${
                      active
                        ? "border-[var(--as-accent)] bg-[color-mix(in_srgb,var(--as-accent)_12%,transparent)]"
                        : "border-[var(--as-border)] hover:border-[var(--as-accent)]"
                    }`}
                    data-testid={`focus-area-${key}`}
                  >
                    <Icon
                      className={`mt-0.5 h-5 w-5 shrink-0 ${active ? "text-[var(--as-accent)]" : "text-[var(--as-muted-fg)]"}`}
                      aria-hidden
                    />
                    <span className="block">
                      <span className="block text-sm font-medium text-[var(--as-fg)]">
                        {t(labelKey, { defaultValue: label })}
                      </span>
                      <span className="mt-0.5 block text-xs text-[var(--as-muted-fg)]">
                        {hint}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </ProfileSectionCard>
    );
  }
);
