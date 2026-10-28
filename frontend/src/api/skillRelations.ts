import { api } from "@/api/client";

export interface SkillRelationSkill {
  id: string;
  key: string;
  label: string;
  status: string;
  evidence_quote: string | null;
}

export interface SkillRelationRow {
  id: string;
  relation: "is_a" | "synonym" | "part_of" | "related_to";
  status: "proposed" | "approved" | "rejected";
  source: "manual" | "llm" | "import" | "derived";
  confidence: number | null;
  evidence: Record<string, unknown> | null;
  decided_by: string | null;
  decided_at: string | null;
  created_at: string;
  updated_at: string;
  from_skill: SkillRelationSkill;
  to_skill: SkillRelationSkill;
  alias_candidate: boolean;
}

export interface SkillRelationThresholds {
  min_support: number;
  batch_size: number;
  max_pairs_per_run: number;
  min_negative_confidence: number;
}

export interface SkillRelationRunLedger {
  candidates: number;
  batches: number;
  judged_batches: number;
  failed_batches: number;
  uncovered: number;
  derived: number;
  edges_proposed: number;
  negatives: number;
  dropped: number;
  below_bar: number;
  materialized: number;
  backfilled: number;
  capped: boolean;
  watermark: string | null;
}

export interface SkillRelationRun {
  id: string;
  status: string;
  created_at: string;
  finished_at: string | null;
  error: string | null;
  ledger: SkillRelationRunLedger;
}

export interface SkillRelationSaveAlias {
  relation: SkillRelationRow;
  target: SkillRelationSkill;
  aliases: string[];
}

export async function fetchSkillRelations(
  status?: SkillRelationRow["status"],
  skillId?: string,
): Promise<SkillRelationRow[]> {
  const { data } = await api.get<SkillRelationRow[]>("/admin/skill-relations", {
    params: { status, skill_id: skillId },
  });
  return data;
}

export async function createSkillRelation(body: {
  from_skill: string;
  to_skill: string;
  relation: SkillRelationRow["relation"];
  confidence?: number | null;
}): Promise<SkillRelationRow> {
  const { data } = await api.post<SkillRelationRow>("/admin/skill-relations", body);
  return data;
}

export async function acceptSkillRelation(id: string): Promise<SkillRelationRow> {
  const { data } = await api.post<SkillRelationRow>(`/admin/skill-relations/${id}/accept`);
  return data;
}

export async function dismissSkillRelation(id: string): Promise<SkillRelationRow> {
  const { data } = await api.post<SkillRelationRow>(`/admin/skill-relations/${id}/dismiss`);
  return data;
}

export async function saveSkillRelationAlias(id: string): Promise<SkillRelationSaveAlias> {
  const { data } = await api.post<SkillRelationSaveAlias>(
    `/admin/skill-relations/${id}/save-alias`,
  );
  return data;
}

export async function removeSkillRelation(id: string): Promise<void> {
  await api.delete(`/admin/skill-relations/${id}`);
}

export async function fetchSkillRelationThresholds(): Promise<SkillRelationThresholds> {
  const { data } = await api.get<SkillRelationThresholds>("/admin/skill-relations/thresholds");
  return data;
}

export async function saveSkillRelationThresholds(
  body: SkillRelationThresholds,
): Promise<SkillRelationThresholds> {
  const { data } = await api.put<SkillRelationThresholds>(
    "/admin/skill-relations/thresholds",
    body,
  );
  return data;
}

export async function fetchSkillRelationRuns(): Promise<SkillRelationRun[]> {
  const { data } = await api.get<SkillRelationRun[]>("/admin/skill-relations/runs");
  return data;
}
