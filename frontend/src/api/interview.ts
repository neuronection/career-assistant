import { api } from "./client";
import type {
  InterviewQuestion,
  InterviewSessionCreate,
  InterviewSessionOut,
} from "@/types/interview";

export async function createInterviewSession(
  body: InterviewSessionCreate
): Promise<InterviewSessionOut> {
  const { data } = await api.post<InterviewSessionOut>(
    "/interview/sessions",
    body
  );
  return data;
}

export async function fetchInterviewSessions(): Promise<
  InterviewSessionOut[]
> {
  const { data } = await api.get<InterviewSessionOut[]>("/interview/sessions");
  return data;
}

export async function fetchInterviewSession(
  id: string
): Promise<InterviewSessionOut> {
  const { data } = await api.get<InterviewSessionOut>(
    `/interview/sessions/${id}`
  );
  return data;
}

export async function patchInterviewPlan(
  id: string,
  items: InterviewQuestion[]
): Promise<InterviewSessionOut> {
  const { data } = await api.patch<InterviewSessionOut>(
    `/interview/sessions/${id}/plan`,
    { items }
  );
  return data;
}

export async function startInterviewSession(
  id: string
): Promise<InterviewSessionOut> {
  const { data } = await api.post<InterviewSessionOut>(
    `/interview/sessions/${id}/start`
  );
  return data;
}

export async function debriefInterviewSession(
  id: string
): Promise<InterviewSessionOut> {
  const { data } = await api.post<InterviewSessionOut>(
    `/interview/sessions/${id}/debrief`
  );
  return data;
}

export async function retryInterviewWeakAreas(
  id: string
): Promise<InterviewSessionOut> {
  const { data } = await api.post<InterviewSessionOut>(
    `/interview/sessions/${id}/retry`
  );
  return data;
}
