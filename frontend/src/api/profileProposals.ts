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
): Promise<ProfileProposalResolveResponse> {
  const { data } = await api.post<ProfileProposalResolveResponse>(
    `/me/profile-proposals/${id}/approve`,
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

export interface ProfileProposalPreviewData {
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  edits: ProfileProposalPreviewEdits;
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
