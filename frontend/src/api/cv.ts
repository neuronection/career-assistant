import { api } from "./client";
import type {
  CoverLetterBriefOut,
  CoverLetterCreate,
  CoverLetterSuggestionOut,
  CvCompileOut,
  CvContextRef,
  CvContextSelection,
  CvContextSourcesOut,
  CvContextStatusOut,
  CvDocumentCreate,
  CvDocumentOut,
  CvDocumentUpdate,
  CvGenerateRequest,
  CvGeneratePreviewOut,
  CvLintReport,
  CvPreviewOut,
  CvRunOut,
  CvSuggestionOut,
  CvSynthGenerateOut,
  CvSynthGenerateRequest,
  CvSynthItem,
  CvSynthPayload,
  CvSynthPreview,
  CvVersionOut,
} from "@/types/cv";
import type { CvAssistantState } from "@/types/cvAssistant";
import type { CvDesignTokens } from "@/types/cvTemplate";

export async function fetchCvs(): Promise<CvDocumentOut[]> {
  const { data } = await api.get<CvDocumentOut[]>("/cv");
  return data;
}

export async function createCv(body: CvDocumentCreate): Promise<CvDocumentOut> {
  const { data } = await api.post<CvDocumentOut>("/cv", body);
  return data;
}

export async function fetchCv(id: string): Promise<CvDocumentOut> {
  const { data } = await api.get<CvDocumentOut>(`/cv/${id}`);
  return data;
}

export async function patchCv(
  id: string,
  body: CvDocumentUpdate
): Promise<CvDocumentOut> {
  const { data } = await api.patch<CvDocumentOut>(`/cv/${id}`, body);
  return data;
}

export async function deleteCv(id: string): Promise<void> {
  await api.delete(`/cv/${id}`);
}

export async function fetchContextSources(): Promise<CvContextSourcesOut> {
  const { data } = await api.get<CvContextSourcesOut>("/cv/context/sources");
  return data;
}

export async function setContext(
  id: string,
  context: CvContextSelection
): Promise<CvDocumentOut> {
  const { data } = await api.put<CvDocumentOut>(`/cv/${id}/context`, context);
  return data;
}

export async function fetchContextStatus(
  id: string
): Promise<CvContextStatusOut> {
  const { data } = await api.get<CvContextStatusOut>(`/cv/${id}/context/status`);
  return data;
}

export async function previewCv(id: string): Promise<CvPreviewOut> {
  const { data } = await api.post<CvPreviewOut>(`/cv/${id}/preview`);
  return data;
}

export async function compileCv(id: string): Promise<CvCompileOut> {
  const { data } = await api.post<CvCompileOut>(`/cv/${id}/compile`);
  return data;
}

export async function fetchVersions(id: string): Promise<CvVersionOut[]> {
  const { data } = await api.get<CvVersionOut[]>(`/cv/${id}/versions`);
  return data;
}

export async function fetchVersionPreview(
  id: string,
  version: number
): Promise<string> {
  const { data } = await api.get<string>(
    `/cv/${id}/versions/${version}/preview`,
    { responseType: "text" }
  );
  return typeof data === "string" ? data : String(data);
}

export async function restoreVersion(id: string, version: number): Promise<CvDocumentOut> {
  const { data } = await api.post<CvDocumentOut>(
    `/cv/${id}/versions/${version}/restore`
  );
  return data;
}

export async function duplicateCv(id: string): Promise<CvDocumentOut> {
  const { data } = await api.post<CvDocumentOut>(`/cv/${id}/duplicate`);
  return data;
}

export type CvExportFormat = "pdf" | "docx" | "md" | "json" | "ats_text";

export async function exportCv(id: string, format: CvExportFormat): Promise<Blob> {
  const { data } = await api.post(`/cv/${id}/export`, { format }, {
    responseType: "blob",
  });
  return data as Blob;
}

export async function fetchLint(id: string): Promise<CvLintReport> {
  const { data } = await api.get<CvLintReport>(`/cv/${id}/lint`);
  return data;
}

export async function aiAction(
  id: string,
  action: "summary" | "bullet" | "compaction" | "tailor" | "gaps" | "translate",
  body: Record<string, unknown> = {}
): Promise<CvSuggestionOut> {
  const { data } = await api.post<CvSuggestionOut>(`/cv/${id}/ai/${action}`, body);
  return data;
}

export async function createCoverLetter(
  body: CoverLetterCreate
): Promise<CvDocumentOut> {
  const { data } = await api.post<CvDocumentOut>("/cv/cover-letters", body);
  return data;
}

export async function generateCv(
  body: CvGenerateRequest
): Promise<{ job_id: string; status: string }> {
  const { data } = await api.post<{ job_id: string; status: string }>(
    "/cv/generate",
    body
  );
  return data;
}

export async function previewSynthMatches(body: {
  language: string;
  target_posting_id?: string;
  refs?: { source_key: string; item_id: string }[];
  context?: CvContextSelection;
}): Promise<CvSynthPreview> {
  const { data } = await api.post<CvSynthPreview>("/cv/synth/preview", body);
  return data;
}

export async function fetchGeneratePreview(
  jobId: string
): Promise<CvGeneratePreviewOut> {
  const { data } = await api.get<CvGeneratePreviewOut>(
    `/cv/generate/${jobId}/preview`
  );
  return data;
}

export async function polishCv(
  cvId: string,
  resumedFrom?: string
): Promise<{ job_id: string; status: string }> {
  const { data } = await api.post<{ job_id: string; status: string }>(
    `/cv/${cvId}/polish`,
    resumedFrom ? { resumed_from: resumedFrom } : {}
  );
  return data;
}

export async function fetchCoverLetterBrief(
  postingId: string
): Promise<CoverLetterBriefOut> {
  const { data } = await api.get<CoverLetterBriefOut>("/cv/cover-letters/brief", {
    params: { posting_id: postingId },
  });
  return data;
}

export async function draftCoverLetter(
  id: string,
  body: { tone?: string; length?: string } = {}
): Promise<CoverLetterSuggestionOut> {
  const { data } = await api.post<CoverLetterSuggestionOut>(
    `/cv/${id}/ai/cover_letter`,
    body
  );
  return data;
}

// — Synthesized variant library (plan 62)

export async function fetchSynthItems(
  params: {
    status?: string;
    source_key?: string;
    language?: string;
    posting_id?: string;
    stale?: boolean;
  } = {}
): Promise<CvSynthItem[]> {
  const { data } = await api.get<CvSynthItem[]>("/cv/synth", { params });
  return data;
}

export async function createSynthItem(body: {
  refs: CvContextRef[];
  scope: "item" | "summary";
  payload: CvSynthPayload;
  variant_key?: string;
  target_posting_id?: string;
  voice?: { language?: string; tone?: string; length?: string };
}): Promise<CvSynthItem> {
  const { data } = await api.post<CvSynthItem>("/cv/synth", body);
  return data;
}

export async function generateSynthItems(
  body: CvSynthGenerateRequest
): Promise<CvSynthGenerateOut> {
  const { data } = await api.post<CvSynthGenerateOut>("/cv/synth/generate", body);
  return data;
}

export async function regenerateSynthItem(id: string): Promise<CvSynthGenerateOut> {
  const { data } = await api.post<CvSynthGenerateOut>(`/cv/synth/${id}/regenerate`);
  return data;
}

export async function patchSynthItem(
  id: string,
  body: {
    payload?: CvSynthPayload;
    status?: "draft" | "active" | "archived";
    variant_key?: string;
  }
): Promise<CvSynthItem> {
  const { data } = await api.patch<CvSynthItem>(`/cv/synth/${id}`, body);
  return data;
}

export async function deleteSynthItem(id: string): Promise<void> {
  await api.delete(`/cv/synth/${id}`);
}

export async function fetchCvRuns(cvId: string): Promise<CvRunOut[]> {
  const { data } = await api.get<CvRunOut[]>(`/cv/${cvId}/runs`);
  return data;
}

export async function fetchCvDesign(
  cvId: string
): Promise<{
  design: CvDesignTokens;
  template: { id: string; title: string; owned: boolean; ats_safe: boolean } | null;
}> {
  const { data } = await api.get(`/cv/${cvId}/design`);
  return data;
}

export async function applyCvOps(
  cvId: string,
  ops: Record<string, unknown>[]
): Promise<{
  results: { op: string; ok: boolean; detail: string }[];
  state: CvAssistantState;
}> {
  const { data } = await api.post(`/cv/${cvId}/ops`, { ops });
  return data;
}
