import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Quote } from "lucide-react";
import i18next from "i18next";

import type { NormalizedSkill } from "./skills";

export const PRIORITY_STYLES: Record<string, string> = {
  must_have: "bg-rose-50 text-rose-700",
  nice_to_have: "bg-amber-50 text-amber-700",
  bonus: "bg-slate-100 text-slate-500",
};

/**
 * Level dots (1–10, filled = required level) — the repo-wide 1–10 scale.
 */
export function LevelDots({ level }: { level: number }) {
  return (
    <span
      className="inline-flex gap-0.5"
      data-testid="skill-level-dots"
      aria-label={i18next.t("postingDetail.levelAria", { level })}
    >
      {Array.from({ length: 10 }, (_, i) => (
        <span
          key={i}
          className={`w-1.5 h-1.5 rounded-full ${i < level ? "bg-primary-600" : "bg-slate-200"}`}
        />
      ))}
    </span>
  );
}

/**
 * Compact chip: label + level + mention count. The priority comes from
 * the group heading, so it is not repeated on every chip.
 */
export function CompactSkillChip({ skill }: { skill: NormalizedSkill }) {
  const unmappedTitle = skill.unmapped
    ? ` · ${i18next.t("postingDetail.unmappedTooltip")}`
    : "";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs ${
        skill.unmapped
          ? "border border-dashed border-slate-300 text-slate-500"
          : "border border-slate-200"
      }`}
      title={`${skill.label} — ${i18next.t("postingDetail.levelAria", { level: skill.level })}${unmappedTitle}`}
    >
      <span className="font-medium text-slate-700">{skill.label}</span>
      <LevelDots level={skill.level} />
      {skill.count > 1 ? (
        <span className="text-[10px] text-slate-400">×{skill.count}</span>
      ) : null}
    </span>
  );
}

/**
 * Detailed chip: everything, with the evidence quote one click away.
 */
export function SkillChip({ skill }: { skill: NormalizedSkill }) {
  const { t } = useTranslation();
  const [showQuote, setShowQuote] = useState(false);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs ${
        skill.unmapped
          ? "border border-dashed border-slate-300"
          : "border border-slate-200"
      }`}
    >
      <span className="font-medium text-slate-700">{skill.label}</span>
      <LevelDots level={skill.level} />
      {skill.count > 1 ? (
        <span
          className="text-[10px] text-slate-400"
          title={i18next.t("postingDetail.mentions", { count: skill.count })}
        >
          ×{skill.count}
        </span>
      ) : null}
      <span className={`px-1.5 py-0.5 rounded text-[10px] ${PRIORITY_STYLES[skill.priority]}`}>
        {t(`postingDetail.priority.${skill.priority}`, {
          defaultValue: skill.priority.replace(/_/g, " "),
        })}
      </span>
      {skill.evidence ? (
        <>
          <button
            type="button"
            aria-label={t("postingDetail.showEvidence")}
            title={skill.evidence}
            onClick={() => setShowQuote((v) => !v)}
            className="text-slate-300 hover:text-primary-600"
          >
            <Quote className="w-3 h-3" />
          </button>
          {showQuote && (
            <em
              className="text-slate-400 border-l border-slate-200 pl-1.5 max-w-56"
              data-testid="skill-evidence"
            >
              “{skill.evidence}”
            </em>
          )}
        </>
      ) : null}
    </span>
  );
}
