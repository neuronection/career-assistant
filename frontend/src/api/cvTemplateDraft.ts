import { api } from "./client";
import type { CvTemplateSummary } from "@/types/cvTemplate";
import type { TemplateContent } from "@/types/cvTemplate";

export interface CvTheme {
  key: string;
  label: string;
  description: string;
  accent_color: string;
  heading_color: string;
  design: Partial<TemplateContent["design"]>;
}

export async function fetchThemes(): Promise<CvTheme[]> {
  const { data } = await api.get<CvTheme[]>("/cv/templates/themes");
  return data;
}

export async function createTemplate(body: {
  title: string;
  content: TemplateContent;
  description?: string;
}): Promise<CvTemplateSummary> {
  const { data } = await api.post<CvTemplateSummary>("/cv/templates", body);
  return data;
}

export async function publishTemplateVersion(
  templateId: string,
  body: { title: string; content: TemplateContent; description?: string }
): Promise<CvTemplateSummary> {
  const { data } = await api.patch<CvTemplateSummary>(
    `/cv/templates/${templateId}`,
    body
  );
  return data;
}

export async function duplicateTemplate(templateId: string): Promise<CvTemplateSummary> {
  const { data } = await api.post<CvTemplateSummary>(
    `/cv/templates/${templateId}/duplicate`
  );
  return data;
}

export async function previewTemplateDraft(content: TemplateContent): Promise<string> {
  const { data } = await api.post<string>(
    "/cv/templates/preview-draft",
    { content },
    { responseType: "text" }
  );
  return typeof data === "string" ? data : String(data);
}
