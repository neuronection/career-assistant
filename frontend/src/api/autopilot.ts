import { api } from "./client";

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
  evidence: { quotes?: string[]; breakdown?: Record<string, unknown>; verified?: boolean };
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
  filters?: Record<string, unknown>;
  rationale?: string;
  found?: number;
  error?: string;
  seen?: number;
  never?: number;
  cooldown?: number;
  kept?: number;
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

export async function fetchGoalRuns(goalId: string): Promise<AutopilotRunWithFindings[]> {
  const { data } = await api.get<AutopilotRunWithFindings[]>(
    `/autopilot/goals/${goalId}/runs`
  );
  return data;
}

export async function fetchFindingsByRun(): Promise<AutopilotRunWithFindings[]> {
  const { data } = await api.get<AutopilotRunWithFindings[]>("/autopilot/findings");
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
