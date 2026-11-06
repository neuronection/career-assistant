import { api, apiDetail } from "@/api/client";

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
    job_proposals: number;
    paths: number;
    translations: number;
    total: number;
  };
}

export interface JobProposalCatalogCandidate {
  code: string;
  title: string;
  family_key: string;
  family_label: string;
  short_description: string;
  score: number;
  source: "exact" | "containment" | "skill" | "semantic";
}

export interface JobProposalDuplicateCandidate {
  code: string;
  title: string;
  score: number;
  reason: "exact" | "containment" | "trigram";
}

/** One keyset window of an admin queue (plan 206): the rows, the opaque
 * cursor for the next window and — on the first window only — the whole
 * queue's size. */
export interface TaxonomyQueuePage<T> {
  items: T[];
  next_cursor: string | null;
  total: number | null;
}

/** One catalog-v2 enrichment proposal awaiting review: the stored patch
 * (known keys render typed, unknown keys collapse into a disclosure) and
 * when the sweep proposed it. */
export interface EnrichmentRow {
  id: string;
  code: string;
  title: string;
  proposal: Record<string, unknown> | null;
  proposed_at: string | null;
}

/** A posting-sourced catalog-job-type proposal awaiting moderation (plan 202). */
export interface JobProposalRow {
  id: string;
  ref: string;
  title: string;
  org: string | null;
  url: string | null;
  proposal: {
    proposal_version?: number;
    action?: "map_existing" | "create";
    job_type?: string;
    existing_job_code?: string | null;
    family_key?: string | null;
    title_norm?: string;
    posting_title?: string;
    short_description?: string;
    skills?: Array<{
      skill_key?: string | null;
      raw_label?: string | null;
      required_level?: number | null;
      priority?: string | null;
    }>;
    seniority?: string | null;
    confidence?: number | null;
    rationale?: string | null;
    needs_edit?: boolean;
    extract_version?: number | null;
    proposed_at?: string;
  } | null;
  proposed_at: string | null;
  suggested_family_key: string | null;
  mapping_signals: Record<string, unknown> | null;
  extract_version: number | null;
  existing_job: {
    code: string;
    title: string;
    status: string;
    family_key: string;
    short_description: string;
  } | null;
  catalog_candidates: JobProposalCatalogCandidate[];
  duplicate_candidates: JobProposalDuplicateCandidate[];
}

export interface JobProposalQueuePage extends TaxonomyQueuePage<JobProposalRow> {
  legacy_count: number;
}

export async function fetchJobProposals(
  cursor: string | null = null,
  limit = 50,
): Promise<JobProposalQueuePage> {
  const { data } = await api.get<JobProposalQueuePage>("/admin/postings/job-proposals", {
    params: { cursor: cursor ?? undefined, limit },
  });
  return data;
}

/** One window of the catalog-v2 enrichment queue (plan 206). The proposal
 * itself is the untyped dict the sweep stored; the cards render the known
 * keys and collapse the rest into the raw disclosure. */
export async function fetchEnrichmentQueue(
  cursor: string | null = null,
  limit = 25,
): Promise<TaxonomyQueuePage<EnrichmentRow>> {
  const { data } = await api.get<TaxonomyQueuePage<EnrichmentRow>>("/admin/jobs/enrichment", {
    params: { cursor: cursor ?? undefined, limit },
  });
  return data;
}

export async function regenerateJobProposals(
  payload: { limit?: number; posting_ids?: string[] } = {},
): Promise<{ queued: boolean; job_id: string; created: boolean }> {
  const { data } = await api.post("/admin/postings/job-proposals/regenerate", payload);
  return data;
}

/** Re-run the catalog join for one posting without paying the extract
 * again (plan 185 S6.4). MANUAL postings are refused server-side. A
 * deferred semantic pass reports itself, so the caller never claims it
 * finished synchronously (plan 50 P2c.4). */
export async function remapPosting(id: string): Promise<{ queued: boolean; job_id: string }> {
  const { data } = await api.post(`/admin/postings/${id}/remap`);
  return data;
}

export interface CatalogMappingSettings {
  job_proposals: boolean;
  semantic_rescue: boolean;
  semantic_rerank: boolean;
}

export async function fetchCatalogMappingSettings(): Promise<CatalogMappingSettings> {
  const { data } = await api.get<CatalogMappingSettings>("/admin/catalog-mapping/settings");
  return data;
}

export async function putCatalogMappingSettings(
  patch: Partial<CatalogMappingSettings>,
): Promise<CatalogMappingSettings> {
  const { data } = await api.put<CatalogMappingSettings>("/admin/catalog-mapping/settings", patch);
  return data;
}

export async function applyJobProposal(
  id: string,
  payload: {
    family_key?: string;
    code?: string;
    title?: string;
    short_description?: string;
    allow_duplicate?: boolean;
    allow_invalid_title?: boolean;
  },
): Promise<{ job_code: string; near_duplicates?: JobProposalDuplicateCandidate[] }> {
  const { data } = await api.post(`/admin/postings/${id}/job-proposal/apply`, payload);
  return data;
}

export async function mapJobProposal(
  id: string,
  jobCode: string,
): Promise<{ job_code: string; job_id: string }> {
  const { data } = await api.post(`/admin/postings/${id}/job-proposal/map`, {
    job_code: jobCode,
  });
  return data;
}

export async function dismissJobProposal(id: string): Promise<void> {
  await api.post(`/admin/postings/${id}/job-proposal/dismiss`);
}

export interface DuplicateJobTypeJob {
  id: string;
  code: string;
  title: string;
  family_key: string;
  created_at: string | null;
  posting_count: number;
}

export interface DuplicateJobTypeGroup {
  normalized_title: string;
  jobs: DuplicateJobTypeJob[];
}

export async function fetchDuplicateJobTypes(): Promise<{ groups: DuplicateJobTypeGroup[] }> {
  const { data } = await api.get<{ groups: DuplicateJobTypeGroup[] }>(
    "/admin/jobs/duplicate-types",
  );
  return data;
}

export async function mergeJobTypes(
  duplicateId: string,
  targetId: string,
): Promise<{
  postings: number;
  remap_queued: number;
  skills: number;
  tags: number;
  relations: number;
  departments: number;
  match_insights: number;
  career_paths: number;
  growth_plans: number;
  snapshots: number;
  audit_event: string;
}> {
  const { data } = await api.post(`/admin/jobs/${duplicateId}/merge`, {
    target_id: targetId,
  });
  return data;
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

export type InterestBulkAction = "deprecate" | "restore" | "delete";

/** Interest tags have no server bulk endpoint — the surface still calls ONE
 * `(ids, action)` function and gets per-item outcomes (plan 200, plan-144
 * report shape); this loops here, never in a component. */
export async function bulkInterestAction(
  ids: string[],
  action: InterestBulkAction,
): Promise<SkillBulkResult> {
  const affected: string[] = [];
  const failed: SkillBulkFailure[] = [];
  for (const id of ids) {
    try {
      if (action === "delete") {
        await deleteTag("interests", id);
      } else {
        await updateTag("interests", id, { deprecated: action === "deprecate" });
      }
      affected.push(id);
    } catch (err) {
      failed.push({ id, key: "", reason: apiDetail(err) });
    }
  }
  return { affected, failed };
}

export interface BulkActionResult {
  affected: string[];
  failed: { id: string; reason: string }[];
  warning?: string | null;
}

const ENRICHMENT_CHUNK = 100;

export type EnrichmentBulkAction = "apply" | "reject";

/** Apply or reject enrichment proposals — the server caps one call at 100
 * (the batch refit scales with it), so larger selections chunk. */
export async function bulkEnrichmentAction(
  ids: string[],
  action: EnrichmentBulkAction,
): Promise<BulkActionResult> {
  const results: BulkActionResult[] = [];
  for (let start = 0; start < ids.length; start += ENRICHMENT_CHUNK) {
    const { data } = await api.post<BulkActionResult>("/admin/jobs/enrichment/bulk", {
      ids: ids.slice(start, start + ENRICHMENT_CHUNK),
      action,
    });
    results.push(data);
  }
  return {
    affected: results.flatMap((result) => result.affected),
    failed: results.flatMap((result) => result.failed),
    warning:
      results
        .map((result) => result.warning)
        .filter(Boolean)
        .join(" ") || null,
  };
}

export type PathBulkAction = "publish" | "reject";

/** Path moderation has per-id endpoints (a published path is a status flip,
 * a rejected draft deletes itself and its steps) — the loop stays here. */
export async function bulkPathAction(
  ids: string[],
  action: PathBulkAction,
): Promise<BulkActionResult> {
  const affected: string[] = [];
  const failed: { id: string; reason: string }[] = [];
  for (const id of ids) {
    try {
      await api.post(`/admin/paths/${id}/${action}`);
      affected.push(id);
    } catch (err) {
      failed.push({ id, reason: apiDetail(err) });
    }
  }
  return { affected, failed };
}

/** Job proposals batch dismiss only — applying one needs a family, code and
 * title per row, so apply stays on the card (plan 200). */
export async function bulkJobProposalDismiss(ids: string[]): Promise<BulkActionResult> {
  const affected: string[] = [];
  const failed: { id: string; reason: string }[] = [];
  for (const id of ids) {
    try {
      await api.post(`/admin/postings/${id}/job-proposal/dismiss`);
      affected.push(id);
    } catch (err) {
      failed.push({ id, reason: apiDetail(err) });
    }
  }
  return { affected, failed };
}
