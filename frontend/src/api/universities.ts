import { api } from "./client";
import type {
  Admission,
  ChatMessage,
  ChatSession,
  Department,
  DocumentRecord,
  JobDepartmentLink,
  University,
  UniversityDetail,
} from "@/types";

export async function fetchUniversities(params: Record<string, unknown> = {}): Promise<University[]> {
  const { data } = await api.get<University[]>("/universities", { params });
  return data;
}

export async function createUniversity(body: Partial<University>): Promise<University> {
  const { data } = await api.post<University>("/universities", body);
  return data;
}

export async function fetchUniversity(id: string): Promise<UniversityDetail> {
  const { data } = await api.get<UniversityDetail>(`/universities/${id}`);
  return data;
}

export async function addDepartment(universityId: string, body: Partial<Department>): Promise<Department> {
  const { data } = await api.post<Department>(`/universities/${universityId}/departments`, body);
  return data;
}

export async function addAdmission(
  departmentId: string,
  body: Partial<Admission>
): Promise<Admission> {
  const { data } = await api.post<Admission>(`/universities/departments/${departmentId}/admissions`, body);
  return data;
}

export async function createJobLink(body: Partial<JobDepartmentLink>): Promise<JobDepartmentLink> {
  const { data } = await api.post<JobDepartmentLink>("/universities/job-links", body);
  return data;
}

export async function uploadDocument(
  file: File,
): Promise<{ document: DocumentRecord; job_id: string }> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post<{ document: DocumentRecord; job_id: string }>(
    "/documents",
    form,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}

export async function fetchDocuments(): Promise<DocumentRecord[]> {
  const { data } = await api.get<DocumentRecord[]>("/documents");
  return data;
}

export async function fetchDocument(id: string): Promise<DocumentRecord> {
  const { data } = await api.get<DocumentRecord>(`/documents/${id}`);
  return data;
}

export async function applyDocument(id: string): Promise<{ applied: Record<string, number> }> {
  const { data } = await api.post(`/documents/${id}/apply`);
  return data;
}

export async function createChatSession(body: { title?: string; context?: Record<string, unknown> } = {}): Promise<ChatSession> {
  const { data } = await api.post<ChatSession>("/chat/sessions", body);
  return data;
}

export async function fetchChatSessions(): Promise<ChatSession[]> {
  const { data } = await api.get<ChatSession[]>("/chat/sessions");
  return data;
}

export async function fetchMessages(sessionId: string): Promise<ChatMessage[]> {
  const { data } = await api.get<ChatMessage[]>(`/chat/sessions/${sessionId}/messages`);
  return data;
}

export async function sendMessage(sessionId: string, content: string): Promise<ChatMessage[]> {
  const { data } = await api.post<ChatMessage[]>(`/chat/sessions/${sessionId}/messages`, { content });
  return data;
}

export async function quickAssist(body: { question: string; page: string; job_code?: string }): Promise<{ answer: string; referenced_job_codes: string[] }> {
  const { data } = await api.post("/ai/assist", body);
  return data;
}
