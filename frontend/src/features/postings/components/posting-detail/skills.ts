import type { PostingDetailSkill } from "@/types/wire";

/**
 * The display model for one real-world skill: deduplicated across the
 * extractor's mentions (the same skill is often required several times
 * with different levels/priorities) — level keeps the strongest demand,
 * priority the strictest, and the mention count is shown as "×N".
 */
export interface NormalizedSkill {
  /** skill_key when mapped, else the normalized raw label. */
  key: string;
  label: string;
  unmapped: boolean;
  level: number;
  priority: string;
  priorityRank: number;
  count: number;
  evidence: string;
  confidence: number;
}

export interface SkillGroup {
  priority: string;
  rank: number;
  skills: NormalizedSkill[];
}

const PRIORITY_RANK: Record<string, number> = {
  must_have: 2,
  nice_to_have: 1,
  bonus: 0,
};

export function normalizeSkills(skills: PostingDetailSkill[]): NormalizedSkill[] {
  const byKey = new Map<string, NormalizedSkill>();
  for (const skill of skills) {
    const unmapped = !skill.skill_key;
    const rawLabel = (skill.raw_label ?? "").trim();
    const key = unmapped ? `raw:${rawLabel.toLowerCase()}` : `key:${skill.skill_key}`;
    const label = unmapped ? rawLabel : (skill.skill_key ?? "").trim();
    const rank = PRIORITY_RANK[skill.priority] ?? 0;
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, {
        key,
        label: label || skill.skill_key || "?",
        unmapped,
        level: skill.required_level,
        priority: skill.priority,
        priorityRank: rank,
        count: 1,
        evidence: skill.evidence_quote,
        confidence: skill.confidence,
      });
      continue;
    }
    existing.level = Math.max(existing.level, skill.required_level);
    if (rank > existing.priorityRank) {
      existing.priorityRank = rank;
      existing.priority = skill.priority;
    }
    existing.count += 1;
    existing.confidence = Math.max(existing.confidence, skill.confidence);
  }
  // importance first: strictest priority, then the highest demanded level
  return [...byKey.values()].sort(
    (a, b) =>
      b.priorityRank - a.priorityRank ||
      b.level - a.level ||
      a.label.localeCompare(b.label),
  );
}

export function groupByPriority(skills: NormalizedSkill[]): SkillGroup[] {
  const groups = new Map<number, SkillGroup>();
  for (const skill of skills) {
    const group =
      groups.get(skill.priorityRank) ??
      ({ priority: skill.priority, rank: skill.priorityRank, skills: [] } as SkillGroup);
    group.skills.push(skill);
    groups.set(skill.priorityRank, group);
  }
  return [...groups.values()].sort((a, b) => b.rank - a.rank);
}

/** The `GET /skills/{key}` address for a chip: mapped keys drop the
 * `key:` dedup prefix; raw labels try their normalized form (a miss is
 * the peek's pending-review state, never an error). */
export function skillAddress(skill: NormalizedSkill): string {
  return skill.key.replace(/^(?:key|raw):/, "");
}
