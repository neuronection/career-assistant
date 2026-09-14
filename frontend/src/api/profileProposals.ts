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
