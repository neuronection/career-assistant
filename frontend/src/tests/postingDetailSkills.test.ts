import { describe, expect, it } from "vitest";

import { groupByPriority, normalizeSkills } from "@/features/postings/components/posting-detail/skills";
import type { PostingDetailSkill } from "@/types/wire";

function skill(overrides: Partial<PostingDetailSkill>): PostingDetailSkill {
  return {
    skill_key: null,
    raw_label: "Something",
    required_level: 5,
    priority: "must_have",
    evidence_quote: "quote",
    confidence: 0.9,
    ...overrides,
  };
}

describe("normalizeSkills", () => {
  it("dedupes mentions of the same skill: max level, strictest priority, mention count", () => {
    const normalized = normalizeSkills([
      skill({ skill_key: "programming", raw_label: null, required_level: 6, priority: "must_have" }),
      skill({ skill_key: "programming", raw_label: null, required_level: 8, priority: "bonus" }),
      skill({ skill_key: "programming", raw_label: null, required_level: 4, priority: "must_have" }),
    ]);
    expect(normalized).toHaveLength(1);
    expect(normalized[0].level).toBe(8);
    expect(normalized[0].priority).toBe("must_have");
    expect(normalized[0].count).toBe(3);
  });

  it("keeps unmapped labels distinct from mapped keys and drops the (unmapped) noise", () => {
    const normalized = normalizeSkills([
      skill({ skill_key: null, raw_label: "Docker" }),
      skill({ skill_key: null, raw_label: "docker" }),
    ]);
    expect(normalized).toHaveLength(1);
    expect(normalized[0].label).toBe("Docker");
    expect(normalized[0].unmapped).toBe(true);
  });

  it("orders by importance: must-have first, then highest level", () => {
    const normalized = normalizeSkills([
      skill({ skill_key: null, raw_label: "Bonus thing", required_level: 9, priority: "bonus" }),
      skill({ skill_key: null, raw_label: "Must thing", required_level: 3, priority: "must_have" }),
      skill({ skill_key: null, raw_label: "Must hard", required_level: 9, priority: "must_have" }),
    ]);
    expect(normalized.map((s) => s.label)).toEqual(["Must hard", "Must thing", "Bonus thing"]);
  });

  it("groups by priority with must-have first", () => {
    const normalized = normalizeSkills([
      skill({ skill_key: null, raw_label: "Bonus thing", priority: "bonus" }),
      skill({ skill_key: null, raw_label: "Must thing", priority: "must_have" }),
    ]);
    const groups = groupByPriority(normalized);
    expect(groups.map((g) => g.priority)).toEqual(["must_have", "bonus"]);
  });
});
