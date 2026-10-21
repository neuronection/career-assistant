import { api } from "./client";
import type {
  ApplicationDetail,
  ApplicationList,
  ApplicationOutcome,
  ApplicationStage,
  ApplicationVia,
  FollowupRules,
  FollowupSurface,
} from "@/types/application";

export interface ApplicationListParams {
  stage?: ApplicationStage;
  open_only?: boolean;
  q?: string;
}

export interface TrackApplicationBody {
  posting_id: string;
  stage?: ApplicationStage;
  applied_via?: ApplicationVia;
  applied_via_url?: string;
  deadline_at?: string | null;
  cv_id?: string | null;
  cover_letter_id?: string | null;
  notes?: string;
}

export async function fetchApplications(
  params: ApplicationListParams = {}
): Promise<ApplicationList> {
  const { data } = await api.get<ApplicationList>("/me/applications", { params });
  return data;
}

export async function fetchApplication(id: string): Promise<ApplicationDetail> {
  const { data } = await api.get<ApplicationDetail>(`/me/applications/${id}`);
  return data;
}

export async function trackApplication(
  body: TrackApplicationBody
): Promise<ApplicationDetail> {
  const { data } = await api.post<ApplicationDetail>("/me/applications", body);
  return data;
}

export async function transitionApplication(
  id: string,
  stage: ApplicationStage,
  body = ""
): Promise<ApplicationDetail> {
  const { data } = await api.post<ApplicationDetail>(
    `/me/applications/${id}/transition`,
    { stage, body }
  );
  return data;
}

export async function addApplicationNote(
  id: string,
  text: string
): Promise<ApplicationDetail> {
  const { data } = await api.post<ApplicationDetail>(
    `/me/applications/${id}/notes`,
    { text }
  );
  return data;
}

export async function linkApplicationDocument(
  id: string,
  body: { cv_id?: string | null; cover_letter_id?: string | null }
): Promise<ApplicationDetail> {
  const { data } = await api.post<ApplicationDetail>(
    `/me/applications/${id}/documents`,
    body
  );
  return data;
}

export async function snoozeApplicationFollowup(
  id: string,
  days: number
): Promise<ApplicationDetail> {
  const { data } = await api.post<ApplicationDetail>(
    `/me/applications/${id}/snooze`,
    { days }
  );
  return data;
}

export async function closeApplication(
  id: string,
  outcome: ApplicationOutcome,
  note = ""
): Promise<ApplicationDetail> {
  const { data } = await api.post<ApplicationDetail>(
    `/me/applications/${id}/close`,
    { outcome, note }
  );
  return data;
}

export async function fetchFollowupSurface(): Promise<FollowupSurface> {
  const { data } = await api.get<FollowupSurface>("/me/followups");
  return data;
}

export async function updateFollowupRules(
  patch: Partial<FollowupRules>
): Promise<FollowupRules> {
  const { data } = await api.patch<FollowupRules>("/me/followups", patch);
  return data;
}
