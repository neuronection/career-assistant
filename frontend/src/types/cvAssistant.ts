import type { CvBlock, CvRenderMetrics } from "@/types/cv";
import type { CvDesignTokens } from "@/types/cvTemplate";

export interface CvAssistantOpResult {
  op: string;
  ok: boolean;
  detail: string;
}

export interface CvAssistantCritiqueIssue {
  severity: "minor" | "major";
  area: string;
  message: string;
}

export interface CvAssistantCritique {
  summary: string;
  issues: CvAssistantCritiqueIssue[];
  safe_token_fixes: Record<string, string>;
}

export interface CvAssistantDocumentState {
  id: string;
  title: string;
  kind: string;
  language: string;
  page_size: string;
  max_pages: number;
  status: string;
  template_id: string | null;
  photo_document_id: string | null;
}

/** Terminal `builder_state` SSE payload — the full post-turn builder
 * state the page re-syncs from (server is the single source of truth). */
export interface CvAssistantState {
  document: CvAssistantDocumentState;
  blocks: CvBlock[];
  overrides: Record<string, Record<string, string>>;
  html: string;
  metrics: CvRenderMetrics;
  resolution: { snapshot_index: Record<string, string[]> };
  operations: CvAssistantOpResult[];
  critique: CvAssistantCritique | null;
  version: number | null;
  design?: CvDesignTokens;
}

export const CV_BUILDER_SURFACE = "cv_builder";

export function cvBuilderContext(cvId: string): Record<string, unknown> {
  return { surface: CV_BUILDER_SURFACE, cv_id: cvId };
}
