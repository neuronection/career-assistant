import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiDetail } from "@/api/client";
import {
  fetchMySkills,
  fetchSkillOntology,
  saveMySkills,
  setSkillDeriveEnabled,
  deleteMySkill,
} from "@/api/skills";
import type { SkillSummary } from "@/api/skills";
import { fetchDerivation } from "@/api/experience";
import { ComboboxField } from "@/components/cv/formPrimitives";
import { ProfileSectionCard } from "@/components/profile/ProfileSectionCard";
import { ScaleSlider } from "@/components/ui";
import { slugifyKey } from "@/lib/slug";
import type { UserSkill } from "@/types";

export interface SkillsCardProps {
  complete?: boolean | null;
  onChanged?: () => void;
}

const DEFAULT_LEVEL = 5;

/** Self-reported skills (1–10) + verified skills from assessments and
 * experience derivation, with source badges. Picking from the combobox —
 * or typing a new name — adds the skill immediately at the default level;
 * unknown keys land as `proposed` catalog suggestions server-side. */
export function SkillsCard({ complete = null, onChanged }: SkillsCardProps) {
  const [skills, setSkills] = useState<UserSkill[]>([]);
  const [options, setOptions] = useState<{ label: string; value: string }[]>([]);
  const [derivation, setDerivation] = useState<
    Record<string, { level: number; months: number; claimed_level?: number | null }>
  >({});
  const [saving, setSaving] = useState(false);
  const { t } = useTranslation();
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void (async () => {
      try {
        const [rows, ontology, derived] = await Promise.all([
          fetchMySkills(),
          fetchSkillOntology(),
          fetchDerivation().catch(() => null),
        ]);
        setSkills(rows);
        setDerivation(
          Object.fromEntries(
            (derived?.skills ?? []).map((item) => [item.skill_id, item])
          )
        );
        setOptions(
          ontology.map((s: SkillSummary) => ({
            label: `${s.label} (${s.category})`,
            value: s.key,
          }))
        );
        setLoaded(true);
      } catch (err) {
        setError(apiDetail(err));
        setLoaded(true);
      }
    })();
  }, []);

  const choices = useMemo(() => {
    const known = new Set(options.map((o) => o.value));
    const extra = skills
      .filter((s) => !known.has(s.key))
      .map((s) => ({ value: s.key, label: s.label }));
    return [...options, ...extra];
  }, [options, skills]);

  const persist = async (next: { skill_key: string; level: number }[]) => {
    setSaving(true);
    setError("");
    try {
      setSkills(await saveMySkills(next));
      onChanged?.();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setSaving(false);
    }
  };

  const removeSkill = (key: string) => {
    const next = skills
      .filter((s) => s.key !== key && s.source === "self_report")
      .map((s) => ({ skill_key: s.key, level: s.level }));
    void persist(next);
  };

  const forgetSkill = async (skill: UserSkill) => {
    setSaving(true);
    setError("");
    setSkills((prev) => prev.filter((p) => p.key !== skill.key));
    try {
      await deleteMySkill(skill.skill_id);
      onChanged?.();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setSaving(false);
    }
  };

  const takeOver = (skill: UserSkill) => {
    const next = [
      ...skills
        .filter((s) => s.source === "self_report")
        .map((s) => ({ skill_key: s.key, level: s.level })),
      { skill_key: skill.key, level: skill.level },
    ];
    void persist(next);
  };

  const toggleDerive = async (skill: UserSkill, derive_enabled: boolean) => {
    setSaving(true);
    setError("");
    setSkills((prev) =>
      prev.map((p) =>
        p.key === skill.key ? { ...p, derive_enabled } : p
      )
    );
    try {
      const updated = await setSkillDeriveEnabled(skill.skill_id, derive_enabled);
      setSkills((prev) =>
        prev.map((p) => (p.key === updated.key ? updated : p))
      );
      onChanged?.();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setSaving(false);
    }
  };

  const derivedTitle = (s: UserSkill) => {
    const derived = derivation[s.skill_id];
    if (derived) {
      return t("profileSection.derivedFrom", {
        level: derived.level.toFixed(1),
        months: derived.months,
      });
    }
    return t("profileSection.fromSource", {
      source: s.source.replace(/_/g, " "),
    });
  };

  const addSkill = (raw: string) => {
    if (!raw.trim()) return;
    const key = slugifyKey(raw);
    if (!key || skills.some((s) => s.key === key)) return;
    const next = [
      ...skills
        .filter((s) => s.source === "self_report")
        .map((s) => ({ skill_key: s.key, level: s.level })),
      { skill_key: key, level: DEFAULT_LEVEL },
    ];
    void persist(next);
  };

  const disabledSkills = skills.filter(
    (s) => s.derive_enabled === false && s.hidden !== true
  );

  return (
    <ProfileSectionCard
      name="skills"
      title={t("profileSection.skillsCount", { count: skills.length })}
      description={t("profileSection.skillsBody")}
      complete={complete}
      saveState={saving ? "saving" : "idle"}
      error={error}
    >
      <div className="space-y-3">
        {!loaded && <p className="text-xs text-[var(--as-muted-fg)]">{t("common.loading")}</p>}
        {loaded && skills.length === 0 && (
          <p className="text-sm text-[var(--as-muted-fg)]">
            {t("profileSection.noSkillsYet")}
          </p>
        )}
        <div className="flex justify-end">
          <div className="w-56">
            <ComboboxField
              label={saving ? t("profileSection.adding") : t("profileSection.addSkill")}
              value=""
              onChange={(value) => addSkill(value)}
              options={choices}
              allowCreate
              createLabel={(term) => t("experience.addSkill", { name: term })}
              placeholder={t("profileSection.skillSearchPlaceholder")}
              hideLabel
              testId="add-skill"
            />
          </div>
        </div>
        {skills.length > 0 && (
          <>
            <ul className="space-y-2">
              {skills
                .filter((s) => s.derive_enabled !== false && s.hidden !== true)
                .map((s) => (
              <li key={s.key} className="flex items-center gap-3">
                <span className="w-44 shrink-0 text-sm text-[var(--as-fg)]">
                  {s.label}
                  {s.source !== "self_report" && (
                    <span
                      className="ml-1 inline-block rounded-full bg-[var(--as-muted)] px-1.5 py-0.5 text-[10px] text-[var(--as-muted-fg)]"
                      title={t("profileSection.fromSource", {
                        source: s.source.replace(/_/g, " "),
                      })}
                      data-testid={`skill-source-${s.key}`}
                    >
                      {s.source.replace(/_/g, " ")}
                    </span>
                  )}
                </span>
                {s.source === "self_report" ? (
                  <div className="min-w-0 flex-1" data-testid={`skill-slider-${s.key}`}>
                    <ScaleSlider
                      value={s.level}
                      min={1}
                      max={10}
                      ariaLabel={t("shared.weightAria", { label: s.label })}
                      onChange={(v) => {
                        const level = typeof v === "number" ? v : s.level;
                        setSkills((prev) =>
                          prev.map((p) => (p.key === s.key ? { ...p, level } : p))
                        );
                      }}
                      onPointerUp={() => {
                        if (s.level === undefined) return;
                        const next = skills
                          .filter((row) => row.source === "self_report")
                          .map((row) => ({
                            skill_key: row.key,
                            level: row.key === s.key ? s.level : row.level,
                          }));
                        void persist(next);
                      }}
                    />
                  </div>
                ) : (
                  <div
                    className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-[var(--as-muted)]"
                    title={derivedTitle(s)}
                  >
                    <div
                      className={`h-1.5 rounded-full ${
                        s.derive_enabled ? "bg-[var(--as-accent)]" : "bg-[var(--as-muted-fg)]"
                      }`}
                      style={{ width: `${(s.level / 10) * 100}%` }}
                    />
                  </div>
                )}
                <span className="w-8 text-right text-xs text-[var(--as-muted-fg)]">
                  {s.level}/10
                </span>
                {s.source === "self_report" ? (
                  <button
                    type="button"
                    onClick={() => removeSkill(s.key)}
                    className="cursor-pointer rounded p-0.5 text-xs text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-danger)]"
                    aria-label={t("profileSection.removeSkillName", { name: s.label })}
                    data-testid={`skill-remove-${s.key}`}
                  >
                    {t("profileSection.remove")}
                  </button>
                ) : (
                  <span className="flex shrink-0 gap-2">
                    <button
                      type="button"
                      onClick={() => takeOver(s)}
                      className="cursor-pointer rounded p-0.5 text-xs text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-fg)]"
                      aria-label={t("profileSection.takeOverAria", { name: s.label })}
                      title={t("profileSection.takeOverHint")}
                      data-testid={`skill-takeover-${s.key}`}
                    >
                      {t("profileSection.edit")}
                    </button>
                    {s.derive_enabled ? (
                      <>
                        <button
                          type="button"
                          onClick={() => void toggleDerive(s, false)}
                          className="cursor-pointer rounded p-0.5 text-xs text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-danger)]"
                          aria-label={t("profileSection.disableAria", { name: s.label })}
                          title={t("profileSection.disableHint")}
                          data-testid={`skill-disable-${s.key}`}
                        >
                          {t("profileSection.disable")}
                        </button>
                        <button
                          type="button"
                          onClick={() => void forgetSkill(s)}
                          className="cursor-pointer rounded p-0.5 text-xs text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-danger)]"
                          aria-label={t("profileSection.forgetAria", { name: s.label })}
                          title={t("profileSection.forgetHint")}
                          data-testid={`skill-forget-${s.key}`}
                        >
                          {t("profileSection.remove")}
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        onClick={() => void toggleDerive(s, true)}
                        className="cursor-pointer rounded p-0.5 text-xs text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-fg)]"
                        aria-label={t("profileSection.enableAria", { name: s.label })}
                        title={t("profileSection.disableHint")}
                        data-testid={`skill-enable-${s.key}`}
                      >
                        {t("profileSection.enable")}
                      </button>
                    )}
                  </span>
                )}
              </li>
            ))}
            </ul>
            {disabledSkills.length > 0 && (
              <details
                className="rounded-lg border border-[var(--as-border)] p-2"
                data-testid="skill-disabled-group"
              >
                <summary className="cursor-pointer select-none text-xs text-[var(--as-muted-fg)]">
                  {t("profileSection.disabledCount", { count: disabledSkills.length })}
                </summary>
                <ul className="mt-2 space-y-1.5">
                  {disabledSkills.map((s) => (
                    <li
                      key={s.key}
                      className="flex items-center gap-3 opacity-70"
                      data-testid={`skill-disabled-${s.key}`}
                    >
                      <span className="w-44 shrink-0 truncate text-sm text-[var(--as-fg)]">
                        {s.label}
                        <span
                          className="ml-1 inline-block rounded-full bg-[var(--as-muted)] px-1.5 py-0.5 text-[10px] text-[var(--as-muted-fg)]"
                          title={derivedTitle(s)}
                          data-testid={`skill-source-${s.key}`}
                        >
                          {s.source.replace(/_/g, " ")} · {t("profileSection.deriveOff")}
                        </span>
                      </span>
                      <span className="min-w-0 flex-1 text-xs text-[var(--as-muted-fg)]">
                        {t("profileSection.derivedUncounted")}
                      </span>
                      <span className="w-8 text-right text-xs text-[var(--as-muted-fg)]">
                        {s.level}/10
                      </span>
                      <button
                        type="button"
                        onClick={() => void toggleDerive(s, true)}
                        className="cursor-pointer rounded p-0.5 text-xs text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-fg)]"
                        aria-label={t("profileSection.enableAria", { name: s.label })}
                        title={t("profileSection.disableHint")}
                        data-testid={`skill-enable-${s.key}`}
                      >
                        {t("profileSection.enable")}
                      </button>
                      <button
                        type="button"
                        onClick={() => void forgetSkill(s)}
                        className="cursor-pointer rounded p-0.5 text-xs text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-danger)]"
                        aria-label={t("profileSection.forgetAria", { name: s.label })}
                        title={t("profileSection.forgetHint")}
                        data-testid={`skill-forget-${s.key}`}
                      >
                        {t("profileSection.remove")}
                      </button>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </>
        )}
      </div>
    </ProfileSectionCard>
  );
}
