export interface CvContextRef {
  source_key: string;
  item_id: string;
}

export interface CvContextSelection {
  mode: "all" | "none" | "custom";
  include: CvContextRef[];
  exclude: CvContextRef[];
}

export type CvGenerateSectionKind =
  | "summary"
  | "experience"
  | "education"
  | "certifications"
  | "skills"
  | "languages"
  | "achievements"
  | "interests";

export interface CvGenerateRequest {
  target_posting_id?: string | null;
  language?: string;
  tone?: "professional" | "warm" | "concise" | "confident" | null;
  length?: "concise" | "standard" | "detailed";
  max_pages?: number;
  template_id?: string | null;
  include_photo?: boolean;
  sections?: CvGenerateSectionKind[];
  context?: CvContextSelection;
  notes?: string;
}

export interface CvGenerateResult {
  cv_id: string;
  title: string;
  version: number;
  lint: Record<string, unknown>;
  warnings: string[];
  fallback_sections: string[];
  plan_fallback: boolean;
}

export interface CvGenerateStatus {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress: number;
  stage: string | null;
  error: string | null;
  result: CvGenerateResult | null;
  created_at: string;
  finished_at: string | null;
}

export interface CvWorkingContent {
  blocks?: CvBlock[];
  overrides?: Record<string, Record<string, string>>;
  [key: string]: unknown;
}

export interface CvBlock {
  kind: string;
  props?: Record<string, unknown>;
}

export interface CvDocumentOut {
  id: string;
  title: string;
  kind: "resume" | "cover_letter";
  target_posting_id: string | null;
  template_id: string | null;
  photo_document_id: string | null;
  language: string;
  page_size: "a4" | "letter";
  max_pages: number;
  status: "draft" | "final" | "archived";
  working_content: CvWorkingContent;
  context: Partial<CvContextSelection>;
  source_document_id: string | null;
  created_at: string;
  updated_at: string;
  latest_version: number | null;
}

export interface CvDocumentCreate {
  title: string;
  kind?: CvDocumentOut["kind"];
  language?: string;
  page_size?: CvDocumentOut["page_size"];
  max_pages?: number;
  target_posting_id?: string | null;
  template_id?: string | null;
  photo_document_id?: string | null;
  source_document_id?: string | null;
  context?: CvContextSelection;
}

export interface CvDocumentUpdate {
  title?: string;
  status?: CvDocumentOut["status"];
  language?: string;
  page_size?: CvDocumentOut["page_size"];
  max_pages?: number;
  target_posting_id?: string | null;
  template_id?: string | null;
  photo_document_id?: string | null;
  working_content?: CvWorkingContent;
  context?: CvContextSelection;
}

export interface CvContextResolutionRef {
  source_key: string;
  item_id: string;
  label?: string;
  updated_at?: string;
}

export interface CvContextItemInfo {
  item_id: string;
  label: string;
  detail: string;
}

export interface CvContextSourceOut {
  key: string;
  label: string;
  description: string;
  items: CvContextItemInfo[];
}

export interface CvContextSourcesOut {
  sources: CvContextSourceOut[];
}

export interface CvRenderMetrics {
  estimated_lines?: number;
  lines_per_page?: number;
  estimated_pages?: number;
  empty_blocks?: string[];
  truncated?: number;
  overflow?: boolean;
  max_pages?: number;
  page_size?: string;
  [key: string]: unknown;
}

export interface CvPreviewOut {
  html: string;
  metrics: CvRenderMetrics;
  blocks: CvBlock[];
  resolution: {
    snapshot: Record<string, unknown>;
    snapshot_index: Record<string, string[]>;
    items: CvContextResolutionRef[];
    resolved_at: string;
  };
}

export interface CvVersionOut {
  id: string;
  version: number;
  content: Record<string, unknown>;
  context_resolution: {
    resolved_at?: string;
    items?: CvContextResolutionRef[];
  };
  content_hash: string;
  created_by: string;
  created_at: string;
}

export interface CvCompileOut {
  version: CvVersionOut;
  html: string;
  metrics: CvRenderMetrics;
}

export interface CvContextStatusOut {
  has_baseline: boolean;
  stale: boolean;
  changed: CvContextResolutionRef[];
  added: CvContextResolutionRef[];
  removed: CvContextResolutionRef[];
}

export interface CvLintCheck {
  id: string;
  level: "pass" | "info" | "warn" | "fail";
  message: string;
}

export interface CvLintReport {
  score: number;
  passed: boolean;
  checks: CvLintCheck[];
  metrics: CvRenderMetrics;
  resolved_items: number;
}

export interface CvProposal {
  ref?: CvContextRef;
  field?: string;
  text: string;
  rationale: string;
  evidence_refs: CvContextRef[];
}

export interface VerifiedProposal {
  proposal: CvProposal;
  verified: boolean;
}

export interface CoverageEntry {
  skill_key: string;
  label: string;
  priority: string;
  user_level: number | null;
}

export interface TailorCoverage {
  covered: CoverageEntry[];
  missing: CoverageEntry[];
}

export interface SectionGap {
  source_key: string;
  label: string;
  message: string;
  candidate_count: number;
}

export interface CvSuggestionOut {
  action: string;
  notes: string;
  proposals: VerifiedProposal[];
  coverage: TailorCoverage | null;
  gaps: SectionGap[];
}

export interface LetterParagraph {
  text: string;
  evidence_refs: CvContextRef[];
}

export interface CoverLetterDraft {
  subject: string;
  salutation: string;
  paragraphs: LetterParagraph[];
  closing: string;
}

export interface VerifiedParagraph {
  text: string;
  evidence_refs: CvContextRef[];
  verified: boolean;
}

export interface CoverLetterSuggestionOut {
  action: "cover_letter";
  notes: string;
  draft: CoverLetterDraft;
  paragraphs: VerifiedParagraph[];
}

export interface BriefSkill {
  skill_key: string;
  label: string;
  required_level: number;
  priority: string;
  evidence_quote: string;
  user_level: number | null;
}

export interface BriefFitDimension {
  dimension: string;
  score: number;
  detail: string;
}

export interface CoverLetterBriefOut {
  posting_id: string;
  posting_title: string;
  org: string;
  location: string;
  extract_ready: boolean;
  must_have: BriefSkill[];
  nice_to_have: BriefSkill[];
  responsibilities: string[];
  fit: {
    score: number | null;
    estimate: boolean;
    dimensions: BriefFitDimension[];
  };
  coverage: TailorCoverage;
  goal: string;
  evidence_items: number;
}

export interface CoverLetterCreate {
  posting_id: string;
  title?: string;
  base_cv_id?: string;
  language?: string;
}
