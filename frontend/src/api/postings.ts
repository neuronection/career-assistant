import { api } from "@/api/client";
import type { PostingsResponse, PostingSourceInfo } from "@/types/wire";
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
  company?: string;
  no_company?: string;
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
