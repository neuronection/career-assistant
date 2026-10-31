import { api } from "@/api/client";

export interface ProfileUsage {
  use_skills: boolean;
  use_education: boolean;
  use_languages: boolean;
  use_location: boolean;
  use_experience: boolean;
  use_lifestyle: boolean;
  stage_source: "profile" | "goal";
}

export const DEFAULT_PROFILE_USAGE: ProfileUsage = {
  use_skills: true,
  use_education: true,
  use_languages: true,
  use_location: true,
  use_experience: true,
  use_lifestyle: true,
  stage_source: "profile",
};

export interface ProfileContextSnapshot {
  skills?: { key: string; level: number }[];
  education_level?: string | null;
  languages?: { code: string; level: string }[];
  country?: string | null;
  city?: string | null;
  stage?: string;
  stage_source?: "profile" | "goal";
  lifestyle_count?: number;
  target_seniority?: string[];
}

export async function fetchProfileContext(
  profile: ProfileUsage,
  seniority: string[]
): Promise<ProfileContextSnapshot> {
  const { data } = await api.post("/autopilot/profile-context", { profile, seniority });
  return data;
}

export interface AutopilotConstraints {
  must_terms: string[];
  never_terms: string[];
  family_keys: string[];
  source_keys: string[];
  remote: boolean | null;
  salary_min: number | null;
  seniority: string[];
  exclude_seen: boolean;
  cooldown_days: number;
  top_n: number;
  profile: ProfileUsage;
}

export interface AutopilotBudget {
  max_tokens: number | null;
  max_calls: number | null;
}

export interface AutopilotRunSummary {
  id: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  tokens_used: number;
  searches_executed: TimelineEntry[];
  error: string;
  created_at: string;
}

export interface AutopilotGoal {
  id: string;
  goal_text: string;
  constraints: AutopilotConstraints;
  budget: AutopilotBudget;
  cadence: { type: string; params: Record<string, unknown> } | null;
  status: "active" | "paused";
  last_run_at: string | null;
  created_at: string;
  updated_at: string;
  last_run: AutopilotRunSummary | null;
  open_findings: number;
}

export interface AutopilotFinding {
  id: string;
  posting_id: string;
  ref: string;
  title: string;
  org: string;
  url: string;
  score: number;
  why: string;
  evidence: {
    quotes?: string[];
    breakdown?: Record<string, unknown>;
    verified?: boolean;
    must_coverage?: { hits: number; total: number };
  };
  feedback: "more_like_this" | "hide_like_this" | null;
  dismissed_at: string | null;
  created_at: string;
}

export interface AutopilotRunWithFindings extends AutopilotRunSummary {
  goal_id?: string;
  findings: AutopilotFinding[];
}

export interface TimelineEntry {
  step: string;
  query?: string;
  queries?: string[];
  filters?: Record<string, unknown>;
  rationale?: string;
  found?: number;
  examined?: number;
  error?: string;
  seen?: number;
  never?: number;
  cooldown?: number;
  kept?: number;
}

export interface AutopilotTraceStep {
  step: string;
  kind: string;
  iteration: number;
  at: string;
  duration_ms: number;
  args: Record<string, unknown>;
  output: Record<string, unknown>;
  error: string;
  abort: string;
}

export interface AutopilotAiCall {
  id: string;
  task_type: string;
  run_stage: string | null;
  provider: string;
  model: string;
  status: string;
  tokens_in: number | null;
  tokens_out: number | null;
  latency_ms: number | null;
  prompt_version: string | null;
}

export interface AutopilotRunDetail {
  run: AutopilotRunSummary & { goal_id: string; goal_text: string };
  steps: AutopilotTraceStep[];
  nodes: string[];
  ai_calls: AutopilotAiCall[];
  findings: AutopilotFinding[];
  timeline: TimelineEntry[];
  trace_available: boolean;
}

export interface GoalCreateInput {
  goal_text: string;
  constraints?: Partial<AutopilotConstraints>;
  budget?: Partial<AutopilotBudget>;
  cadence?: { type: string; params: Record<string, unknown> } | null;
}

export interface GoalUpdateInput {
  goal_text?: string;
  constraints?: Partial<AutopilotConstraints>;
  budget?: Partial<AutopilotBudget>;
  status?: "active" | "paused";
  cadence?: { type: string; params: Record<string, unknown> };
  remove_cadence?: boolean;
}

export async function fetchGoals(): Promise<AutopilotGoal[]> {
  const { data } = await api.get<AutopilotGoal[]>("/autopilot/goals");
  return data;
}

export async function createGoal(input: GoalCreateInput): Promise<{ id: string }> {
  const { data } = await api.post("/autopilot/goals", input);
  return data;
}

export async function patchGoal(
  goalId: string,
  input: GoalUpdateInput
): Promise<{ id: string; status: string }> {
  const { data } = await api.patch(`/autopilot/goals/${goalId}`, input);
  return data;
}

export async function deleteGoal(goalId: string): Promise<void> {
  await api.delete(`/autopilot/goals/${goalId}`);
}

export async function runGoal(
  goalId: string
): Promise<{ run_id: string; status: string; findings: { posting_id: string }[] }> {
  const { data } = await api.post(`/autopilot/goals/${goalId}/run`);
  return data;
}
export async function fetchFindingsByRun(): Promise<AutopilotRunWithFindings[]> {
  const { data } = await api.get<AutopilotRunWithFindings[]>("/autopilot/findings");
  return data;
}

export async function fetchRunDetail(runId: string): Promise<AutopilotRunDetail> {
  const { data } = await api.get<AutopilotRunDetail>(`/autopilot/runs/${runId}`);
  return data;
}

export async function sendFindingFeedback(
  findingId: string,
  feedback: "more_like_this" | "hide_like_this"
): Promise<{ learned_terms: string[]; goal_paused: boolean }> {
  const { data } = await api.post(`/autopilot/findings/${findingId}/feedback`, {
    feedback,
  });
  return data;
}
