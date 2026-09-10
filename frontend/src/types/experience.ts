export interface AchievementIn {
  text: string;
  metric: { kind: string; value: number; unit: string } | null;
}

export interface ExperienceSkillIn {
  skill_key: string;
  role_in_item: "primary" | "secondary" | "exposure";
  level_claim: number | null;
  last_used: string | null;
}

export interface ExperienceItemIn {
  title: string;
  kind: "job" | "project" | "internship" | "volunteer" | "freelance";
  org_name: string;
  start: string | null;
  end: string | null;
  open_ended: boolean;
  hours_per_week: number | null;
  onsite_policy: "onsite" | "hybrid" | "remote" | null;
  description: string;
  links: Record<string, unknown>[];
  source: "self_report" | "cv_parse" | "assessment" | "import";
  status: "draft" | "active";
  skills: ExperienceSkillIn[];
  achievements: AchievementIn[];
}

export interface ExperienceItemUpdate {
  title?: string;
  kind?: ExperienceItemIn["kind"];
  org_name?: string;
  start?: string | null;
  end?: string | null;
  open_ended?: boolean;
  hours_per_week?: number | null;
  onsite_policy?: ExperienceItemIn["onsite_policy"];
  description?: string;
  links?: Record<string, unknown>[];
  status?: "draft" | "active";
  skills?: ExperienceSkillIn[];
  achievements?: AchievementIn[];
}

export interface ExperienceSkillOut {
  skill_id: string;
  skill_key: string;
  skill_label: string;
  role_in_item: "primary" | "secondary" | "exposure";
  level_claim: number | null;
  last_used: string | null;
}

export interface AchievementOut {
  id: string;
  text: string;
  metric: { kind: string; value: number; unit: string } | null;
}

export interface ExperienceItemOut {
  id: string;
  kind: ExperienceItemIn["kind"];
  title: string;
  org_name: string;
  org_id: string | null;
  start: string;
  end: string | null;
  open_ended: boolean;
  hours_per_week: number | null;
  onsite_policy: string | null;
  description: string;
  links: Record<string, unknown>[];
  source: ExperienceItemIn["source"];
  status: "draft" | "active";
  created_at: string;
  skills: ExperienceSkillOut[];
  achievements: AchievementOut[];
}

export interface DerivedSkillOut {
  skill_id: string;
  skill_label: string;
  months: number;
  level: number;
  confidence: number;
  supporting_items: string[];
}

export interface EvidenceOut {
  skill_id: string;
  items: {
    id: string;
    source: string;
    experience_item: { id: string; title: string; kind: string } | null;
    level_value: number | null;
    confidence: number | null;
    note: string;
    claimed_at: string;
  }[];
}
