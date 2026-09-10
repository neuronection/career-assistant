import { api } from "./client";
import type { DocumentRecord } from "@/types";
import type {
  CvApplyReport,
  CvDraft,
  CvIntakeSection,
  CvSelections,
  DraftHistoryRow,
} from "@/types/cvIntake";
import { AxiosError } from "axios";

export function isNotFound(err: unknown): boolean {
  return err instanceof AxiosError && err.response?.status === 404;
}

export async function uploadCv(
  file: File
): Promise<{ document: DocumentRecord; job_id: string }> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post<{
    document: DocumentRecord;
    job_id: string;
  }>("/documents", form, {
    headers: { "Content-Type": "multipart/form-data" },
    params: { kind: "cv" },
  });
  return data;
}

export async function getCvDrafts(documentId: string): Promise<CvDraft> {
  const { data } = await api.get<CvDraft>(`/cv/intake/${documentId}/drafts`);
  return data;
}

export async function applyCvDraft(
  documentId: string,
  selections: CvSelections
): Promise<{ report: CvApplyReport }> {
  const { data } = await api.post<{ report: CvApplyReport }>(
    `/cv/intake/${documentId}/apply`,
    { selections }
  );
  return data;
}

export async function discardCvDraft(documentId: string): Promise<void> {
  await api.post(`/cv/intake/${documentId}/discard`);
}

export async function reparseCv(
  documentId: string
): Promise<{ job_id: string }> {
  const { data } = await api.post<{ job_id: string }>(
    `/cv/intake/${documentId}/parse`
  );
  return data;
}

export async function listCvDocuments(): Promise<DocumentRecord[]> {
  const { data } = await api.get<DocumentRecord[]>("/documents", {
    params: { kind: "cv" },
  });
  return data;
}

export async function listCvDraftHistory(): Promise<DraftHistoryRow[]> {
  const { data } = await api.get<DraftHistoryRow[]>("/cv/intake/drafts");
  return data;
}

export async function deleteCvDocument(documentId: string): Promise<void> {
  await api.delete(`/documents/${documentId}`);
}

async function blobUrl(url: string): Promise<string> {
  const { data } = await api.get(url, { responseType: "blob" });
  return URL.createObjectURL(data as Blob);
}

export function fetchCvFileUrl(documentId: string): Promise<string> {
  return blobUrl(`/documents/${documentId}/file`);
}

export function fetchCvPageImageUrl(
  documentId: string,
  pageIndex: number
): Promise<string> {
  return blobUrl(`/documents/${documentId}/pages/${pageIndex}/image`);
}

export const CV_INTAKE_SECTIONS: CvIntakeSection[] = [
  "basics",
  "education",
  "experience",
  "skills",
  "languages",
  "certifications",
  "awards",
  "interests",
];
