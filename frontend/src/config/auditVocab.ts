import type { AuditBreakdownRow } from "@/api/audit";

/** Display-side task categorization (plan 151 D4): the backend stays a
 * generic per-task aggregation; the dashboard groups tasks into six
 * categories for the overview chart and the AI-activity filter. */
export const AUDIT_CATEGORIES = [
  "chat",
  "cv",
  "catalog",
  "matching",
  "documents",
  "ops",
] as const;

export type AuditCategory = (typeof AUDIT_CATEGORIES)[number];

const TASK_CATEGORY: Record<string, AuditCategory> = {
  chat: "chat",
  chat_ops: "chat",
  chat_title: "chat",
  assist: "chat",
  interview_plan: "chat",
  interview_turn: "chat",
  interview_debrief: "chat",
  template_design: "cv",
  cv_ocr: "cv",
  cv_parse: "cv",
  cv_template_design: "cv",
  cv_template_review: "cv",
  cv_template_pick: "cv",
  cv_build_review: "cv",
  cv_suggest: "cv",
  cv_cover_letter: "cv",
  cv_builder_chat: "cv",
  cv_draft: "cv",
  cv_synth: "cv",
  job_generate: "catalog",
  relation_suggest: "catalog",
  skill_relation_suggest: "catalog",
  posting_map: "catalog",
  posting_extract: "catalog",
  detail_triage: "catalog",
  company_triage: "catalog",
  target_resolve: "catalog",
  catalog_enrich: "catalog",
  query_curator: "catalog",
  translate: "catalog",
  assessment_generate: "matching",
  profile_analyze: "matching",
  match_score: "matching",
  path_suggest: "matching",
  path_draft: "matching",
  university_parse: "documents",
  transcribe: "documents",
  embed: "ops",
  mcp_tool_call: "ops",
  sandbox_capability_call: "ops",
  tool_run: "ops",
  autopilot_run: "ops",
  decision: "ops",
  decision_tool_dispatch: "ops",
  decision_boolean_gate: "ops",
  decision_choice: "ops",
  decision_score: "ops",
};

export function categoryOfTask(task: string): AuditCategory {
  return TASK_CATEGORY[task] ?? "ops";
}

export interface CategoryRollupRow {
  category: AuditCategory;
  calls: number;
  errors: number;
}

export function categoryRollup(rows: AuditBreakdownRow[]): CategoryRollupRow[] {
  const byCategory = new Map<AuditCategory, CategoryRollupRow>();
  for (const row of rows) {
    const category = categoryOfTask(row.key);
    const existing = byCategory.get(category) ?? {
      category,
      calls: 0,
      errors: 0,
    };
    existing.calls += row.calls;
    existing.errors += row.errors;
    byCategory.set(category, existing);
  }
  return [...byCategory.values()].sort((a, b) => b.calls - a.calls);
}

export function formatTokens(count: number): string {
  if (count >= 1_000_000) {
    return trimZero(`${(count / 1_000_000).toFixed(1)}M`);
  }
  if (count >= 10_000) return `${Math.round(count / 1_000)}k`;
  if (count >= 1_000) return trimZero(`${(count / 1_000).toFixed(1)}k`);
  return String(count);
}

function trimZero(text: string): string {
  return text.replace(".0", "");
}

export function formatTokensExact(count: number): string {
  return count.toLocaleString();
}

export function formatLatency(ms: number | null): string {
  if (ms == null) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

export function formatBucketLabel(bucket: string, kind: "hour" | "day"): string {
  if (kind === "hour") {
    const time = bucket.split("T")[1] ?? bucket;
    return time.slice(0, 5);
  }
  const date = bucket.split("T")[0] ?? bucket;
  return date.slice(5);
}

export function formatDelta(current: number, previous: number): string {
  if (previous === 0) return current > 0 ? "•" : "—";
  const pct = Math.round(((current - previous) / previous) * 100);
  return `${pct >= 0 ? "+" : ""}${pct}%`;
}
