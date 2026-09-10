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
