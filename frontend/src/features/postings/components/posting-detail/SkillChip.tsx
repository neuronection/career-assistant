import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Quote } from "lucide-react";

import { SkillTag } from "@/components/skills/SkillTag";
import type { NormalizedSkill } from "./skills";

function skillTitle(
  skill: NormalizedSkill,
  t: (key: string, opts?: Record<string, unknown>) => string
): string {
  const parts = [t("card.skillRequires", { level: skill.level })];
  if (skill.count > 1) {
    parts.push(t("postingDetail.mentions", { count: skill.count }));
  }
  if (skill.unmapped) parts.push(t("postingDetail.unmappedTooltip"));
  return parts.join(" · ");
}

export function CompactSkillChip({ skill }: { skill: NormalizedSkill }) {
  const { t } = useTranslation();
  return (
    <SkillTag
      label={skill.label}
      score={skill.level}
      unmapped={skill.unmapped}
      title={skillTitle(skill, t)}
    />
  );
}

export function SkillChip({ skill }: { skill: NormalizedSkill }) {
  const { t } = useTranslation();
  const [showQuote, setShowQuote] = useState(false);
  return (
    <span className="inline-flex items-center gap-1">
      <CompactSkillChip skill={skill} />
      {skill.evidence ? (
        <>
          <button
            type="button"
            aria-label={t("postingDetail.showEvidence")}
            title={skill.evidence}
            onClick={() => setShowQuote((value) => !value)}
            className="text-[var(--as-muted-fg)] hover:text-[var(--as-accent)]"
            data-testid="skill-evidence-toggle"
          >
            <Quote className="h-3 w-3" />
          </button>
          {showQuote ? (
            <em
              className="max-w-56 border-l border-[var(--as-border)] pl-1.5 text-[var(--as-muted-fg)]"
              data-testid="skill-evidence"
            >
              “{skill.evidence}”
            </em>
          ) : null}
        </>
      ) : null}
    </span>
  );
}
