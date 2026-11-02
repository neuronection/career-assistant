import { api } from "@/api/client";
import type { PostingsResponse, PostingSourceInfo } from "@/types/wire";
import type { ExploreResponse, SmartSearchResponse } from "@/types/wire";
import type { PostingDetailOut } from "@/types/wire";
import type { ExploreParams } from "@/types";


export async function reextractPosting(
  postingId: string,
): Promise<{ extracted: boolean; needs_review?: boolean }> {
  const { data } = await api.post(`/admin/postings/${postingId}/extract`);
  return data;
}

// ---------------------------------------------------- filter system (plan 136)

export type SkillExpandMode = "off" | "down" | "related";

export interface FilterSpec {
  v: number;
  skills: {
    include: string[];
    exclude: string[];
    min_level: number | null;
    /** Graph expansion knob (plan 138): exact / sub-skills / +related. */
    expand: SkillExpandMode;
    /** Relation hops for learned edges (1 or 2). */
    hops: 1 | 2;
  };
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
    skills: { include: [], exclude: [], min_level: null, expand: "down", hops: 1 },
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


export async function explorePostings(
  params: ExploreParams
): Promise<ExploreResponse> {
  const { data } = await api.get<ExploreResponse>("/postings/explore", {
    params,
    // repeated params (`org=A&org=B`), never bracketed — org names may
    // contain commas and the backend reads them via getlist
    paramsSerializer: { indexes: null },
  });
  return data;
}

export async function smartSearch(query: string): Promise<SmartSearchResponse> {
  const { data } = await api.post<SmartSearchResponse>("/postings/smart-search", { query });
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
    company?: string;
    no_company?: string;
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
