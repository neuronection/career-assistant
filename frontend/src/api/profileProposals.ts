import { api } from "./client";
import type { ProfileProposalCardData } from "@/types";

export interface ProfileProposalListResponse {
  proposals: ProfileProposalCardData[];
  pending_count: number;
}

export interface ProfileProposalResolveResponse {
  proposal: ProfileProposalCardData;
  applied: { id: string; kind: string; label: string } | null;
  already?: boolean;
}

export async function fetchProfileProposals(
  status?: string,
): Promise<ProfileProposalListResponse> {
  const { data } = await api.get<ProfileProposalListResponse>(
    "/me/profile-proposals",
    { params: status ? { status } : {} },
  );
  return data;
}

export async function approveProfileProposal(
  id: string,
  optionKeys?: string[],
): Promise<ProfileProposalResolveResponse> {
  const { data } = await api.post<ProfileProposalResolveResponse>(
    `/me/profile-proposals/${id}/approve`,
    optionKeys?.length ? { option_keys: optionKeys } : {},
  );
  return data;
}

export async function rejectProfileProposal(
  id: string,
): Promise<ProfileProposalResolveResponse> {
  const { data } = await api.post<ProfileProposalResolveResponse>(
    `/me/profile-proposals/${id}/reject`,
  );
  return data;
}

export async function dismissProfileProposal(id: string): Promise<void> {
  await api.delete(`/me/profile-proposals/${id}`);
}

/** One anchored-edit instruction family (server `_edit_ops`, plan 99) —
 * the source of the preview span highlighting. */
export interface ProfileProposalPreviewEdits {
  text_edits?: {
    field: string;
    op: "replace" | "append" | "prepend";
    find?: string | null;
    text: string;
  }[];
  collection_edits?: {
    collection: string;
    op: "add" | "remove";
    value?: Record<string, unknown> | null;
    match?: Record<string, unknown> | null;
  }[];
}

export interface CvSynthSourceRow {
  source_key: string;
  item_id: string;
  label: string;
  snapshot: Record<string, unknown> | null;
}

export interface ProfileProposalPreviewData {
  /** A single entity snapshot; for `cv_synth` cards a stacked per-ref
   * source list (plan 101 AD2 — after-side stays null). */
  before:
    | Record<string, unknown>
    | CvSynthSourceRow[]
    | null;
  after: Record<string, unknown> | null;
  edits: ProfileProposalPreviewEdits & {
    kind?: string;
    action?: string;
    language?: string;
    resolved_refs?: {
      label: string;
      source_key: string;
      item_id: string;
    }[];
    posting?: string;
    posting_title?: string;
  };
}

export async function getProposalPreview(
  id: string,
): Promise<ProfileProposalPreviewData> {
  const { data } = await api.get<ProfileProposalPreviewData>(
    `/me/profile-proposals/${id}/preview`,
  );
  return data;
}

export async function revertProfileProposal(
  id: string,
): Promise<ProfileProposalCardData> {
  const { data } = await api.post<ProfileProposalCardData>(
    `/me/profile-proposals/${id}/revert`,
  );
  return data;
}
