import { api } from "@/api/client";

export interface HygieneCandidateHint {
  posting_id: string;
  ref: string;
  title: string;
  org: string;
  score: number;
  reason: string;
}

export interface HygieneCandidateRow {
  id: string;
  ref: string;
  title: string;
  org: string;
  candidates: HygieneCandidateHint[];
}

export interface HygieneDuplicateRow {
  id: string;
  ref: string;
  title: string;
  org: string;
  duplicate_of_id: string;
}

export interface HygieneCanonicalRow {
  id: string;
  ref: string;
  title: string;
  org: string;
  repost_count: number;
  last_verified_at: string | null;
}

export interface HygieneOverview {
  canonical: HygieneCanonicalRow[];
  duplicates: HygieneDuplicateRow[];
  candidates: HygieneCandidateRow[];
  counts: { canonical: number; duplicates: number; candidates: number };
}

export async function fetchPostingHygiene(): Promise<HygieneOverview> {
  const { data } = await api.get<HygieneOverview>("/admin/posting-hygiene");
  return data;
}

export async function scanPostingHygiene(): Promise<Record<string, unknown>> {
  const { data } = await api.post<Record<string, unknown>>(
    "/admin/posting-hygiene/scan",
  );
  return data;
}

export async function mergePostingHygiene(
  duplicateId: string,
  canonicalId: string,
): Promise<void> {
  await api.post("/admin/posting-hygiene/merge", {
    duplicate_id: duplicateId,
    canonical_id: canonicalId,
  });
}

export async function clearPostingHygiene(postingId: string): Promise<void> {
  await api.post("/admin/posting-hygiene/clear", { posting_id: postingId });
}
