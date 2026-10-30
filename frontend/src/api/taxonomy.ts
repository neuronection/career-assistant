import { api } from "@/api/client";

export interface Tag {
  id: string;
  key: string;
  label: string;
  category: string;
  description: string;
  deprecated: boolean;
}

export interface SkillRow {
  id: string;
  key: string;
  label: string;
  category: string;
  description: string;
  parent_id: string | null;
  level_anchors: { level: number; label: string; description: string }[];
  aliases: string[];
  status: "proposed" | "active" | "deprecated";
  origin: string;
}

export interface TagInput {
  key?: string;
  label?: string;
  category?: string;
  description?: string;
  deprecated?: boolean;
}

export interface SkillInput {
  label?: string;
  category?: string;
  description?: string;
  status?: "proposed" | "active" | "deprecated";
  aliases?: string[];
}

export interface TaxonomyStats {
  skills: {
    total: number;
    active: number;
    proposed: number;
    deprecated: number;
    auto_promoted: number;
    promoted_7d: number;
  };
  queue: {
    relations: number;
    enrichment: number;
    paths: number;
    translations: number;
    total: number;
  };
}

export async function fetchInterests(includeDeprecated = true): Promise<Tag[]> {
  const { data } = await api.get<Tag[]>("/taxonomy/interests", {
    params: { include_deprecated: includeDeprecated },
  });
  return data;
}

/** Backlog counts behind the taxonomy work-queue bar (plan 161). */
export async function fetchTaxonomyStats(): Promise<TaxonomyStats> {
  const { data } = await api.get<TaxonomyStats>("/admin/taxonomy/stats");
  return data;
}

export async function fetchSkillRows(
  includeDeprecated = true,
  includeProposed = true,
): Promise<SkillRow[]> {
  const { data } = await api.get<SkillRow[]>("/taxonomy/skills", {
    params: {
      include_deprecated: includeDeprecated,
      include_proposed: includeProposed,
    },
  });
  return data;
}

export async function createTag(
  kind: "interests" | "skills",
  body: TagInput,
): Promise<Tag> {
  const { data } = await api.post<Tag>(`/taxonomy/${kind}`, body);
  return data;
}

export async function updateTag(
  kind: "interests" | "skills",
  id: string,
  body: TagInput | SkillInput,
): Promise<Tag | SkillRow> {
  const { data } = await api.put(`/taxonomy/${kind}/${id}`, body);
  return data;
}

export async function deleteTag(
  kind: "interests" | "skills",
  id: string,
): Promise<{ deleted?: string; message?: string; job_refs?: number }> {
  const { data } = await api.delete(`/taxonomy/${kind}/${id}`);
  return data;
}

export async function promoteSkill(id: string): Promise<SkillRow> {
  const { data } = await api.post<SkillRow>(`/admin/skills/${id}/promote`);
  return data;
}

export async function mergeSkill(id: string, targetId: string): Promise<SkillRow> {
  const { data } = await api.post<SkillRow>(`/admin/skills/${id}/merge`, {
    target_id: targetId,
  });
  return data;
}

export type SkillBulkAction = "promote" | "deprecate" | "restore" | "delete" | "merge";

export interface SkillBulkFailure {
  id: string;
  key: string;
  reason: string;
  job_refs?: number | null;
  profile_refs?: number | null;
}

export interface SkillBulkResult {
  affected: string[];
  failed: SkillBulkFailure[];
}

const BULK_CHUNK = 200;

export async function bulkSkillAction(
  ids: string[],
  action: SkillBulkAction,
  targetId?: string,
): Promise<SkillBulkResult> {
  // The bulk contract caps ids at 200 per call (server safety bound) —
  // selections of any size chunk transparently and the results merge.
  const results: SkillBulkResult[] = [];
  for (let start = 0; start < ids.length; start += BULK_CHUNK) {
    const { data } = await api.post<SkillBulkResult>("/admin/skills/bulk", {
      ids: ids.slice(start, start + BULK_CHUNK),
      action,
      target_id: targetId ?? null,
    });
    results.push(data);
  }
  return {
    affected: results.flatMap((result) => result.affected),
    failed: results.flatMap((result) => result.failed),
  };
}
