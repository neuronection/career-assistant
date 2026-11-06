import { SkillsCard } from "../cards";
import type { TabProps } from "./shared";

export function SkillsTab({ data, view, loading, compact, refresh, onDrill }: TabProps) {
  return (
    <SkillsCard
      skills={data.skills}
      loading={loading}
      error={data.errors.skills ?? null}
      onRetry={refresh}
      onSkill={(key) => onDrill(`skills=${encodeURIComponent(key)}`)}
      compact={compact}
      windowName={view.window}
    />
  );
}
