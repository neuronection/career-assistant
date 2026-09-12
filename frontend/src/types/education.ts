export type EducationLevel =
  | "no_formal"
  | "middle_school"
  | "high_school"
  | "vocational"
  | "bachelor"
  | "master"
  | "doctorate";

export type GradeBand =
  | "low"
  | "below_average"
  | "average"
  | "good"
  | "excellent"
  | "unknown";

export interface EducationItemIn {
  institution: string;
  org_name: string;
  program: string;
  level: EducationLevel;
  start: string | null;
  end: string | null;
  in_progress: boolean;
  grade_band: GradeBand | null;
  focus_subjects: string[];
  description: string;
  status: "draft" | "active";
  university_id: string | null;
  department_id: string | null;
}

export interface EducationItemUpdate {
  institution?: string;
  org_name?: string;
  program?: string;
  level?: EducationLevel;
  start?: string | null;
  end?: string | null;
  in_progress?: boolean;
  grade_band?: GradeBand | null;
  focus_subjects?: string[];
  description?: string;
  status?: "draft" | "active";
  university_id?: string | null;
  department_id?: string | null;
}

export interface EducationItemOut {
  id: string;
  institution: string;
  org_name: string;
  program: string;
  level: string;
  start: string | null;
  end: string | null;
  in_progress: boolean;
  grade_band: string | null;
  focus_subjects: string[];
  description: string;
  source: "self_report" | "cv_parse" | "assessment" | "import";
  status: "draft" | "active";
  university_id: string | null;
  department_id: string | null;
  created_at: string;
}

export interface CertificationIn {
  name: string;
  issuer: string;
  issued: string | null;
  expires: string | null;
  credential_id: string;
  link: string;
  language_code: string | null;
  status: "draft" | "active";
}

export interface CertificationUpdate {
  name?: string;
  issuer?: string;
  issued?: string | null;
  expires?: string | null;
  credential_id?: string;
  link?: string;
  language_code?: string | null;
  status?: "draft" | "active";
}

export interface CertificationOut {
  id: string;
  name: string;
  issuer: string;
  issued: string | null;
  expires: string | null;
  credential_id: string;
  link: string;
  language_code: string | null;
  source: "self_report" | "cv_parse" | "assessment" | "import";
  status: "draft" | "active";
  created_at: string;
}

export type AchievementKind =
  | "award"
  | "honor"
  | "publication"
  | "extracurricular";

export interface AchievementIn {
  kind: AchievementKind;
  title: string;
  issuer: string;
  date: string | null;
  detail: string;
  link: string;
  status: "draft" | "active";
}

export interface AchievementUpdate {
  kind?: AchievementKind;
  title?: string;
  issuer?: string;
  date?: string | null;
  detail?: string;
  link?: string;
  status?: "draft" | "active";
}

export interface AchievementOut {
  id: string;
  kind: string;
  title: string;
  issuer: string;
  date: string | null;
  detail: string;
  link: string;
  source: "self_report" | "cv_parse" | "assessment" | "import";
  status: "draft" | "active";
  created_at: string;
}
