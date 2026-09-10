export type InterviewKind =
  | "technical"
  | "behavioral"
  | "mixed"
  | "research";

export type InterviewStatus =
  | "planned"
  | "active"
  | "completed"
  | "abandoned";

export interface InterviewQuestion {
  id: string;
  kind: "technical" | "behavioral" | "research";
  skill_key: string | null;
  skill_label: string;
  target_level: number | null;
  question: string;
  focus: string;
}

export interface InterviewPlan {
  items: InterviewQuestion[];
  rationale: string;
}

export interface InterviewDebriefAggregate {
  structure: number;
  evidence: number;
  clarity: number;
  answered: number;
}

export interface InterviewDebriefQuestion {
  question_id: string;
  kind: string | null;
  skill_key: string | null;
  skill_label: string | null;
  question: string | null;
  structure: number;
  evidence: number;
  clarity: number;
  average: number;
  weak: boolean;
}

export interface InterviewDebriefResource {
  skill_key: string | null;
  title: string;
  provider: string;
  url: string;
  kind: string;
}

export interface InterviewDebrief {
  summary: string;
  strengths: string[];
  gaps: string[];
  recommendations: string[];
  aggregate: InterviewDebriefAggregate;
  per_question: InterviewDebriefQuestion[];
  weak_question_ids: string[];
  resources: InterviewDebriefResource[];
}

export interface InterviewSessionOut {
  id: string;
  kind: string;
  status: string;
  role_label: string;
  posting_ref: string | null;
  chat_session_id: string | null;
  plan: InterviewQuestion[];
  rubric_scores: Record<string, unknown>[];
  debrief: InterviewDebrief | null;
  created_at: string;
  updated_at: string;
}

export interface InterviewSessionCreate {
  posting_ref?: string;
  job_code?: string;
  kind: InterviewKind;
}
