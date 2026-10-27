import { api } from "@/api/client";
import type { PostingsResponse, PostingOut, PostingSourceInfo } from "@/types/wire";
import type { ExploreResponse } from "@/types/wire";
import type { PostingDetailOut } from "@/types/wire";
import type { ExploreParams } from "@/types";

export interface PostingSearchParams {
  skills: string;
  mode?: "all" | "any";
  priority?: string;
  source?: string;
  remote?: boolean;
  seniority?: string;
  catalog_job_id?: string;
  saved?: boolean;
  sort?: string;
  match_profile?: boolean;
}

export async function reextractPostings(
  postingIds: string[],
): Promise<{ queued: number; skipped: number; missing: string[]; requested: number }> {
  const { data } = await api.post<
    { queued: number; skipped: number; missing: string[]; requested: number }
  >(
    "/admin/postings/reextract",
    { posting_ids: postingIds },
  );
  return data;
}

export async function reextractPosting(
  postingId: string,
): Promise<{ extracted: boolean; needs_review?: boolean }> {
  const { data } = await api.post(`/admin/postings/${postingId}/extract`);
  return data;
}

// ---------------------------------------------------- filter system (plan 136)

export interface FilterSpec {
  v: number;
  skills: { include: string[]; exclude: string[]; min_level: number | null };
  salary: { min: number | null; max: number | null; currency: string | null };
  location: { include: string[]; exclude: string[]; remote_only: boolean | null };
  companies: {
    include: string[];
    exclude: string[];
    industries_include: string[];
    industries_exclude: string[];
  };
  seniority: { min: string | null; max: string | null; exclude: string[] };
  employment: { include: string[]; exclude: string[] };
  work_mode: { include: string[]; exclude: string[] };
  languages: { include: string[]; exclude: string[] };
  education: { include: string[]; exclude: string[] };
  posted_within: { days: number | null };
  match_score: { min: number | null; max: number | null };
  source: { include: string[]; exclude: string[] };
  saved: { value: boolean | null };
  description: { text: string | null };
  sort: string;
}

export function emptyFilterSpec(): FilterSpec {
  return {
    v: 1,
    skills: { include: [], exclude: [], min_level: null },
    salary: { min: null, max: null, currency: null },
    location: { include: [], exclude: [], remote_only: null },
    companies: { include: [], exclude: [], industries_include: [], industries_exclude: [] },
    seniority: { min: null, max: null, exclude: [] },
    employment: { include: [], exclude: [] },
    work_mode: { include: [], exclude: [] },
    languages: { include: [], exclude: [] },
    education: { include: [], exclude: [] },
    posted_within: { days: null },
    match_score: { min: null, max: null },
    source: { include: [], exclude: [] },
    saved: { value: null },
    description: { text: null },
    sort: "fresh",
  };
}

export async function filterPostings(
  filters: FilterSpec,
): Promise<PostingOut[]> {
  const { data } = await api.post<PostingOut[]>("/postings/filter", { filters });
  return data;
}

export interface FilterPreset {
  id: string;
  name: string;
  tags: string[];
  filters: FilterSpec;
  updated_at: string | null;
}

export async function fetchFilterPresets(): Promise<FilterPreset[]> {
  const { data } = await api.get<FilterPreset[]>("/me/posting-filters");
  return data;
}

export async function saveFilterPreset(
  name: string,
  tags: string[],
  filters: FilterSpec,
): Promise<FilterPreset> {
  const { data } = await api.post<FilterPreset>("/me/posting-filters", {
    name,
    tags,
    filters,
  });
  return data;
}

export async function deleteFilterPreset(presetId: string): Promise<void> {
  await api.delete(`/me/posting-filters/${presetId}`);
}

export async function searchPostings(
  params: PostingSearchParams
): Promise<PostingsResponse> {
  const { data } = await api.get<PostingsResponse>("/postings/search", {
    params,
  });
  return data;
}

export async function explorePostings(
  params: ExploreParams
): Promise<ExploreResponse> {
  const { data } = await api.get<ExploreResponse>("/postings/explore", {
    params,
  });
  return data;
}

export async function fetchPostingSources(): Promise<PostingSourceInfo[]> {
  const { data } = await api.get<PostingSourceInfo[]>("/postings/sources");
  return data;
}

export async function fetchPostingDetail(id: string): Promise<PostingDetailOut> {
  const { data } = await api.get<PostingDetailOut>(`/postings/${id}`);
  return data;
}

export async function fetchPostings(
  params: {
    source?: string;
    remote?: boolean;
    seniority?: string;
    catalog_job_id?: string;
    saved?: boolean;
    sort?: string;
  } = {}
): Promise<PostingsResponse> {
  const { data } = await api.get<PostingsResponse>("/postings", { params });
  return data;
}

export async function markPostingsSeen(postingIds: string[]): Promise<{ marked: number }> {
  const { data } = await api.post<{ marked: number }>("/postings/seen", {
    posting_ids: postingIds,
  });
  return data;
}

export async function savePosting(postingId: string, saved: boolean): Promise<void> {
  await api.post("/postings/save", { posting_id: postingId, saved });
}

export async function hidePosting(postingId: string, hidden: boolean): Promise<void> {
  await api.post("/postings/hide", { posting_id: postingId, hidden });
}

export async function markApplied(
  postingId: string,
  appliedViaUrl: string
): Promise<void> {
  await api.post("/postings/applied", {
    posting_id: postingId,
    applied_via_url: appliedViaUrl,
  });
}
