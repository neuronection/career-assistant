import { api } from "@/api/client";
import type {
  ApplicationDetail,
  ApplicationList,
  ApplicationOffer,
  ApplicationOutcome,
  ApplicationStage,
  ApplicationVia,
  FollowupRules,
  FollowupSurface,
} from "@/types/application";
import type { ApplicationKit } from "@/types/wire";

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

export async function setApplicationOffer(
  id: string,
  body: ApplicationOffer
): Promise<ApplicationDetail> {
  const { data } = await api.post<ApplicationDetail>(
    `/me/applications/${id}/offer`,
    body
  );
  return data;
}

export async function clearApplicationOffer(
  id: string
): Promise<ApplicationDetail> {
  const { data } = await api.delete<ApplicationDetail>(
    `/me/applications/${id}/offer`
  );
  return data;
}

export async function fetchApplicationKit(id: string): Promise<ApplicationKit> {
  const { data } = await api.get<ApplicationKit>(`/me/applications/${id}/kit`);
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

export interface IcsProposal {
  uid: string;
  summary: string;
  start: string;
  end: string | null;
  all_day: boolean;
  location: string;
  application_id: string | null;
  application_label: string;
  match_reason: string;
  duplicate: boolean;
  writable: boolean;
}

export interface IcsImportReport {
  proposals: IcsProposal[];
  warnings: string[];
  created: number;
  applied: boolean;
}

export async function importApplicationsIcs(
  ics: string,
  apply = false
): Promise<IcsImportReport> {
  const { data } = await api.post<IcsImportReport>("/me/applications/import/ics", {
    ics,
    apply,
  });
  return data;
}

export interface ApplicationInsights {
  tailored: { n: number; responses: number; rate: number | null };
  untailored: { n: number; responses: number; rate: number | null };
  suppressed: boolean;
  floor: number;
  caveat: string;
  next_action: string;
}

export async function fetchApplicationInsights(): Promise<ApplicationInsights> {
  const { data } = await api.get<ApplicationInsights>("/me/applications/insights");
  return data;
}
