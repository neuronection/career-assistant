export interface FieldEvidence {
  quote: string;
  page: number | null;
  confidence: number;
}

export interface ExtractedLink {
  kind: "linkedin" | "github" | "portfolio" | "other";
  url: string;
  label: string;
  evidence: FieldEvidence;
}

export interface ExtractedBasics {
  full_name: string;
  headline: string;
  email: string;
  phone: string;
  location: string;
  links: ExtractedLink[];
  evidence: FieldEvidence;
}

export interface ExtractedMetric {
  kind: string;
  value: number;
  unit: string;
}

export interface ExtractedSkill {
  name: string;
  level_claim: number | null;
  evidence: FieldEvidence;
}

export interface ExtractedAchievement {
  text: string;
  metric: ExtractedMetric | null;
  evidence: FieldEvidence;
}

export interface ExtractedExperience {
  kind: "job" | "project" | "internship" | "volunteer" | "freelance";
  title: string;
  org: string;
  start: string;
  end: string;
  description: string;
  skills: ExtractedSkill[];
  achievements: ExtractedAchievement[];
  evidence: FieldEvidence;
}

export interface ExtractedEducation {
  institution: string;
  program: string;
  level: string;
  start: string;
  end: string;
  grade_band:
    | "low"
    | "below_average"
    | "average"
    | "good"
    | "excellent"
    | "unknown"
    | null;
  evidence: FieldEvidence;
}

export interface ExtractedLanguage {
  code: string;
  level: "basic" | "intermediate" | "advanced" | "native";
  evidence: FieldEvidence;
}

export interface ExtractedCertification {
  name: string;
  issuer: string;
  issued: string;
  credential_id: string;
  evidence: FieldEvidence;
}

export interface ExtractedAward {
  kind: "award" | "honor" | "publication" | "extracurricular";
  title: string;
  issuer: string;
  date: string;
  evidence: FieldEvidence;
}

export interface ExtractedInterest {
  label: string;
  evidence: FieldEvidence;
}

export interface CvExtractPayload {
  basics: ExtractedBasics;
  summary: string;
  education: ExtractedEducation[];
  experience: ExtractedExperience[];
  skills: ExtractedSkill[];
  languages: ExtractedLanguage[];
  certifications: ExtractedCertification[];
  awards: ExtractedAward[];
  interests: ExtractedInterest[];
}

export type CvIntakeSection =
  | "basics"
  | "education"
  | "experience"
  | "skills"
  | "languages"
  | "certifications"
  | "awards"
  | "interests";

export type CvSelections = Partial<Record<CvIntakeSection, true | number[]>>;

export interface CvAppliedEntity {
  entity_type:
    | "basics"
    | "skills"
    | "experience_items"
    | "education_items"
    | "certifications"
    | "profile_achievements"
    | "user_interest"
    | "academics_languages";
  count: number;
}

export interface CvDraft {
  id: string;
  status: "pending" | "applied" | "discarded";
  payload: CvExtractPayload;
  report: {
    created?: Record<string, number>;
    proposed_skills?: string[];
    skill_conflicts?: unknown[];
    unmapped_interests?: string[];
    duplicates?: unknown[];
  };
  section_count?: number;
  applied?: CvAppliedEntity[];
}

export interface CvApplyReport {
  created: Record<string, number>;
  proposed_skills: string[];
  skill_conflicts: unknown[];
  unmapped_interests: string[];
  duplicates: unknown[];
}

export interface DraftDocumentInfo {
  id: string;
  filename: string;
  mime: string;
  size_bytes: number;
  page_count: number;
  status: string;
  error: string;
  created_at: string | null;
}

export interface DraftHistoryRow {
  document_id: string;
  status: "pending" | "applied" | "discarded";
  updated_at: string | null;
  section_count?: number;
  report: {
    created?: Record<string, number>;
    proposed_skills?: string[];
    skill_conflicts?: unknown[];
    unmapped_interests?: string[];
    duplicates?: unknown[];
  };
  document: DraftDocumentInfo;
}
