import { api } from "./client";
import type { FitBreakdown } from "@/types";

export type AssessmentQuestionKind =
  | "scenario_mcq"
  | "time_allocation"
  | "ranking"
  | "slider";

export interface AssessmentQuestion {
  id: string;
  phase: number;
  kind: AssessmentQuestionKind;
  prompt: string;
  help: string;
  options: {
    id: string;
    label: string;
    detail: string;
    scores: {
      skill_levels?: Record<string, number>;
      interest_keys?: string[];
    };
  }[];
  time_split: Record<string, unknown> | null;
  source: "bank" | "ai";
}

export interface AssessmentState {
  id: string;
  kind: string;
  status: "in_progress" | "completed" | "abandoned";
  phase_order: number[];
  current_phase: number;
  phase_title: string;
  progress: Record<string, { answered: number; total: number; title: string }>;
  context: Record<string, unknown>;
  phase_one_form: boolean;
  questions: AssessmentQuestion[];
}

export interface AssessmentResults {
  run_id: string;
  kind: string;
  status: string;
  skill_levels: { key: string; level: number }[];
  interest_keys: string[];
  selection: Record<string, number>;
  shortlist: { job_id: string; fit_score: number }[];
}

export async function createAssessment(
  kind: string,
  context: Record<string, unknown> = {},
): Promise<AssessmentState> {
  const { data } = await api.post<AssessmentState>("/assessments", {
    kind,
    context,
  });
  return data;
}

export async function fetchAssessments(): Promise<
  { id: string; kind: string; status: string; current_phase: number }[]
> {
  const { data } = await api.get("/assessments");
  return data;
}

export async function fetchAssessment(runId: string): Promise<AssessmentState> {
  const { data } = await api.get<AssessmentState>(`/assessments/${runId}`);
  return data;
}

export async function submitAnswers(
  runId: string,
  answers: { question_id: string; answer: Record<string, unknown> | null }[],
): Promise<{ saved: number }> {
  const { data } = await api.post(`/assessments/${runId}/answers`, { answers });
  return data;
}

export async function advanceAssessment(runId: string): Promise<{
  status: string;
  current_phase?: number;
  effects?: {
    applied_skills: number;
    skill_conflicts: { key: string; self_level: number; assessed_level: number }[];
    interest_keys: string[];
    selection: Record<string, number>;
    rationale_job_id: string;
  };
}> {
  const { data } = await api.post(`/assessments/${runId}/advance`);
  return data;
}

export async function cancelAssessment(runId: string): Promise<{ status: string }> {
  const { data } = await api.post(`/assessments/${runId}/cancel`);
  return data;
}

export async function assistQuestion(
  runId: string,
  questionId: string,
): Promise<{ answer: string }> {
  const { data } = await api.post(`/assessments/${runId}/assist`, {
    question_id: questionId,
  });
  return data;
}

export async function fetchAssessmentResults(
  runId: string,
): Promise<AssessmentResults> {
  const { data } = await api.get<AssessmentResults>(`/assessments/${runId}/results`);
  return data;
}

export type { FitBreakdown };
