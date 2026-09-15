import { api } from "./client";
import type { CvTemplateSummary } from "@/types/cvTemplate";

export async function fetchTemplates(): Promise<CvTemplateSummary[]> {
  const { data } = await api.get<CvTemplateSummary[]>("/cv/templates");
  return data;
}

export async function fetchTemplatePreview(templateId: string): Promise<string> {
  const { data } = await api.get<string>(`/cv/templates/${templateId}/preview`, {
    responseType: "text",
  });
  return typeof data === "string" ? data : String(data);
}

export interface PreviewMetrics {
  estimated_pages?: number;
  empty_blocks?: string[];
  overflow?: boolean;
  lines_per_page?: number;
}

export async function fetchTemplatePreviewWith(
  templateId: string,
  cvId?: string | null
): Promise<{ html: string; metrics: PreviewMetrics }> {
  const { data } = await api.post(`/cv/templates/${templateId}/preview-with`,
    cvId ? { cv_id: cvId } : {}
  );
  return data;
}

export interface TemplateVersionRow {
  id: string;
  version: number;
  title: string;
  created_at: string;
  content_hash: string;
}

export async function fetchTemplateVersions(
  templateId: string
): Promise<TemplateVersionRow[]> {
  const { data } = await api.get<TemplateVersionRow[]>(
    `/cv/templates/${templateId}/versions`
  );
  return data;
}

export interface TemplateDiff {
  from_version: number;
  to_version: number;
  token_changes: { path: string; from: unknown; to: unknown }[];
  block_changes: {
    added: string[];
    removed: string[];
    props_changed: { block: string; area: string }[];
  };
}

export async function fetchTemplateDiff(
  templateId: string,
  against?: string
): Promise<TemplateDiff> {
  const { data } = await api.get<TemplateDiff>(
    `/cv/templates/${templateId}/diff`,
    { params: against ? { against } : {} }
  );
  return data;
}

export async function draftTemplateAi(brief: string): Promise<CvTemplateSummary> {
  const { data } = await api.post<CvTemplateSummary>("/cv/templates/draft-ai", {
    brief,
  });
  return data;
}

export interface TemplatePickSummary {
  template_id: string;
  title: string;
  reason: string;
}

export interface TemplateSuggestions {
  picks: TemplatePickSummary[];
  candidates_considered: number;
}

export async function suggestTemplates(
  payload: { language: string; target_posting_id?: string } = { language: "en" }
): Promise<TemplateSuggestions> {
  const { data } = await api.post<TemplateSuggestions>(
    "/cv/templates/suggest",
    payload
  );
  return data;
}

export async function reviewTemplatePages(
  templateId: string,
  files: File[],
  pageCount = 1
): Promise<{
  lint: Record<string, unknown>;
  critique: { summary: string; issues: { severity: string; area: string; message: string }[]; safe_token_fixes: Record<string, string> } | null;
  note?: string;
}> {
  const form = new FormData();
  form.append("page_count", String(pageCount));
  for (const file of files) form.append("files", file);
  const { data } = await api.post(`/cv/templates/${templateId}/visual-review`, form);
  return data;
}
