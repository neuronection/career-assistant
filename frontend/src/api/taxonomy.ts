import { api } from "./client";

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

export async function fetchInterests(includeDeprecated = true): Promise<Tag[]> {
  const { data } = await api.get<Tag[]>("/taxonomy/interests", {
    params: { include_deprecated: includeDeprecated },
  });
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
