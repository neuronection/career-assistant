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
