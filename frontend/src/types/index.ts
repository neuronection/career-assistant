/**
 * Hand-written view models.
 *
 * Wire types live in `@/types/wire` (named aliases over the generated
 * contract in `@/types/api.gen`). The shapes here narrow JSONB payloads
 * the contract deliberately leaves open (chat message metadata, posting
 * extraction, document extraction), compose several wire calls into one
 * UI shape (JobMatchDetail, JobFamilyNode), or carry SSE payloads that
 * are not part of the OpenAPI surface at all (ProfileProposalCardData,
 * chat previews/attachments). Vocabulary unions for free-string wire
 * fields (severity/channel/template literals) are also view-side.
 */

import type {
  CareerStage,
  DocumentStatus,
  EducationLevel,
  Job,
  MatchInsight,
  NotificationRuleKind,
  OnboardingPath,
  PhysicalActivity,
  ProfileLinkKind,
  ScoringWeights,
} from "@/types/wire";

// ------------------------------------------------------------- skills

export interface LevelAnchor {
  level: number;
  label: string;
  description: string;
}

export type SkillStatus = "proposed" | "active" | "deprecated";

/** Taxonomy tag as the interests UI reads it (the wire row adds admin fields). */
export interface TaxonomyTag {
  key: string;
  label: string;
  category: string;
  description: string;
}

export type PostingSkillPriority = "must_have" | "nice_to_have" | "bonus";

/** Taxonomy tag as the UI reads it (the wire row carries admin fields too). */
export interface TaxonomyTag {
  key: string;
  label: string;
  category: string;
  description: string;
}

/** Skill row; the wire carries level_anchors as free objects. */
export interface Skill {
  id: string;
  key: string;
  label: string;
  category: string;
  description: string;
  parent_id: string | null;
  level_anchors: LevelAnchor[];
  aliases: string[];
  status: SkillStatus;
  origin: string;
}

/** User skill row; the wire carries level_anchors as free objects. */
export interface UserSkill {
  skill_id: string;
  key: string;
  label: string;
  category: string;
  level: number;
  source: "self_report" | "assessment" | "experience" | "ai_inferred" | "document";
  confidence: number;
  level_anchors: LevelAnchor[];
  derive_enabled: boolean;
  hidden?: boolean;
}

// ------------------------------------------------------------- catalog

export interface JobFamilyNode {
  id: string;
  key: string;
  label: string;
  parent_id: string | null;
  path: string;
  level: number;
  description: string;
  job_count: number;
  children: JobFamilyNode[];
}

// -------------------------------------------------------- universities

/** Document row; extraction narrows the wire's free-form payload. */
export interface DocumentRecord {
  id: string;
  kind: string;
  filename: string;
  mime: string;
  size_bytes: number;
  page_count: number;
  status: DocumentStatus;
  error: string;
  created_at?: string | null;
  extraction: {
    universities: {
      name: string;
      country: string;
      city: string;
      university_type: string;
      departments: {
        name: string;
        field_key: string;
        degree: string;
        duration_years: number;
        language: string;
        application_deadline: string | null;
        admissions: {
          year: number;
          baseline_score: number | null;
          top_score: number | null;
          quota: number | null;
          units: string;
          confidence: number;
        }[];
      }[];
    }[];
  } | null;
}

// ---------------------------------------------------------------- chat

/** One assistant-drafted career path riding the message metadata
 * (plan 125) — the chat-side review artifact. */
export interface ChatPathDraftStep {
  kind: string;
  label?: string;
  optional?: boolean;
  parent?: number | null;
  edge_label?: string;
  skill_key?: string | null;
  family_key?: string | null;
  education_level?: string | null;
}

export interface ChatPathDraftMeta {
  draft: {
    title: string;
    description?: string;
    steps: ChatPathDraftStep[];
    job_code?: string | null;
    job_title?: string | null;
  } | null;
  proposed_job?: { code: string; title: string; status: string } | null;
  note?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  parent_id?: string | null;
  variant_index?: number;
  variant_count?: number;
  sibling_ids?: string[];
  /** Persisted turn metadata — the wire carries it as free JSONB. */
  metadata_json: {
    referenced_job_codes?: string[];
    referenced_posting_refs?: string[];
    explore_query?: string;
    model?: string;
    elapsed_ms?: number;
    tokens_in?: number;
    tokens_out?: number;
    tools?: {
      name: string;
      title?: string;
      status?: string;
      start_ms?: number;
      duration_ms?: number;
      args_summary?: string;
      result_summary?: string;
      results?: string[];
    }[];
    nodes?: {
      id: string;
      label?: string;
      status?: string;
      start_ms?: number;
      duration_ms?: number;
    }[];
    stream_interrupted?: boolean;
    surface?: string;
    operations?: { op: string; ok: boolean; detail: string }[];
    critique?: {
      summary: string;
      issues: { severity: "minor" | "major"; area: string; message: string }[];
      safe_token_fixes: Record<string, string>;
    } | null;
    version?: number | null;
    proposals?: ProfileProposalCardData[];
    proposals_dropped?: number;
    proposals_dropped_reasons?: {
      kind?: string | null;
      reason: string;
    }[];
    profile_op_errors?: {
      kind?: string | null;
      code: string;
    }[];
    attachments?: ChatCvAttachment[];
    referenced_cv_ids?: string[];
    template_previews?: ChatTemplatePreview[];
    path_draft?: ChatPathDraftMeta;
  } | null;
  created_at: string;
}

/** One template preview (plan 83): SSE `preview` event and persisted
 * message metadata share the shape — the URL serves the cached PNG. */
export interface ChatTemplatePreview {
  template_id: string;
  title: string;
  url: string;
}

export interface ChatCvAttachment {
  kind: "cv";
  cv_id: string;
  title: string;
}

// ------------------------------------------------- HITL proposal cards

/** Wire shape of one HITL card (SSE `proposal` event, list endpoint and
 * persisted message metadata all share it — the backend serializes once
 * via `proposal_event`, which is not part of the OpenAPI surface). */
export interface ProfileProposalCardData {
  id: string;
  kind: string;
  action: string;
  status: "pending" | "approved" | "rejected" | "conflict" | "expired" | "reverted";
  title: string;
  entity_id?: string | null;
  entity_label?: string;
  diff: ProposalDiffRowView[];
  destructive: boolean;
  source: string;
  /** Non-chat provenance (ADR-0015): MCP token label + request id. */
  origin?: {
    channel?: string;
    token_id?: string;
    token_label?: string;
    request_id?: string;
    tool?: string;
  };
  chat_session_id?: string | null;
  created_at: string;
  /** Picker cards (plan 108): the option list rides the payload. */
  payload?: Record<string, unknown>;
}

/** SSE card rows tolerate a missing label (renderer falls back). */
export type ProposalDiffRowView = {
  field: string;
  label?: string;
  before?: unknown;
  after?: unknown;
};

// --------------------------------------------------------------- jobs

/** The job detail view: composed client-side from job + insight +
 * university pathways (separate wire calls). */
export interface JobMatchDetail {
  job: Job;
  insight: MatchInsight | null;
  university_pathways: {
    department: {
      id: string;
      name: string;
      degree: string;
      duration_years: number;
      application_deadline: string | null;
      university: { id: string; name: string; country: string; city: string };
    };
    relevance: number;
    rationale: string;
    required_subjects: string[];
    typical_position: string;
    employment_rate_pct: number | null;
    admissions: { year: number; baseline_score: number | null; units: string }[];
  }[];
}

// ------------------------------------------------------------ postings

export interface ExploreParams {
  q?: string;
  skills?: string;
  skill_mode?: "all" | "any";
  skill_priority?: string;
  education_min?: string;
  languages?: string;
  posted_within?: string;
  fresh_only?: boolean;
  salary_min?: number;
  salary_currency?: string;
  seniority?: string;
  employment_type?: string;
  remote_policy?: string;
  city?: string;
  country?: string;
  source?: string;
  mapped_family?: string;
  saved?: boolean;
  seen?: boolean;
  applied?: boolean;
  extracted_only?: boolean;
  contract?: string;
  travel?: string;
  schedule?: string;
  benefits?: string;
  org?: string;
  sort?: string;
  cursor?: string;
  limit?: number;
}

// ------------------------------------------------------- notifications

export type NotificationChannel = "in_app" | "desktop" | "browser" | "email" | "webhook";

export type NotificationChannelKey = "in_app" | "desktop" | "browser" | "email" | "webhook";

export type AlertRuleKind = Extract<NotificationRuleKind, "fit_threshold" | "new_in_family">;

export type WebhookTemplate = "generic" | "slack" | "teams" | "telegram" | "ntfy";

// --------------------------------------------------------- profile form

/** The sectioned profile form payload (GET/PUT /profile composes it as
 * a free dict on the wire — sections validate server-side). */
export interface Profile {
  basics: {
    birth_year: number | null;
    education_level: EducationLevel;
    grade: string | null;
    career_stage?: CareerStage | null;
    onboarding_path?: OnboardingPath | null;
    country: string;
    city: string;
    timezone?: string;
    full_name: string;
    email: string;
    phone: string;
    headline: string;
    links?: { kind: ProfileLinkKind; url: string; label: string }[];
  };
  academics: {
    favorite_subjects: { key: string; weight: number }[];
    languages: { code: string; level: string }[];
  };
  career_stage?: CareerStage;
  stage_source?: "derived" | "explicit";
  interests: { tag_key: string; weight: number; source: string }[];
  hobbies: { key: string | null; label: string; weight: number }[];
  likes: { tag_key: string | null; label: string; weight: number }[];
  dislikes: { tag_key: string | null; label: string; weight: number }[];
  aspirations: { label: string; tag_keys: string[]; notes: string }[];
  work_preferences: {
    teamwork: number;
    environment: number;
    structure: number;
    pace: number;
    leadership: number;
    remote_ok: boolean;
    focus_areas: string[];
    salary_priority: number;
    stability_priority: number;
    physical_activity: PhysicalActivity;
    creativity_priority: number;
  };
  preferences: {
    scoring_weights: ScoringWeights;
  };
  constraints: {
    physical_conditions: string[];
    max_education_years: number | null;
    willing_to_relocate: boolean;
    hours_available_per_week: number | null;
    salary_min: number | null;
    salary_negotiable: boolean;
    travel_days_per_month: number | null;
    shift_tolerance: "none" | "occasional" | "regular" | null;
    commute_radius_km: number | null;
  };
  ai_summary: {
    summary: string;
    strengths: string[];
    watchouts: string[];
    suggested_interest_keys: string[];
    suggested_skill_keys: string[];
    model: string;
    generated_at: string | null;
  } | null;
  completeness: {
    percent: number;
    sections: Record<string, boolean>;
    required?: Record<string, boolean>;
    required_percent?: number;
  };
}

// --------------------------------------------------------- career paths

/** One mark a user can put on a path or a step (the backend `PathFlag`
 * vocabulary — marks are preferences, never scoring inputs). */
export type PathMark = "interested" | "dismissed" | "pinned";

/** Structural step input for the view builder — the wire `PathStepOut`
 * shape plus the branch fields the detail API adds. */
export interface PathStepInput {
  id?: string | null;
  position: number;
  kind: string;
  label: string;
  optional?: boolean;
  family_key?: string | null;
  family_label?: string | null;
  skill_key?: string | null;
  skill_label?: string | null;
  education_level?: string | null;
  parent_step_id?: string | null;
  edge_label?: string | null;
}

/** One rendered step of a career path (a view-model node). */
export interface PathViewNode {
  stepId: string;
  position: number;
  kind: string;
  label: string;
  optional: boolean;
  familyKey: string | null;
  familyLabel: string | null;
  skillKey: string | null;
  skillLabel: string | null;
  educationLevel: string | null;
  /** Why this branch exists ("or: research track") — incoming edge label. */
  edgeLabel: string | null;
  /** True when the step hangs off the chain via an explicit parent. */
  branch: boolean;
}

/** A rendered edge; `from`/`to` reference step ids or the reserved
 * `__start__` / `__target__` sentinels. */
export interface PathViewEdge {
  from: string;
  to: string;
  label: string;
  branch: boolean;
}

/** The one typed view model every path projection consumes. */
export interface PathView {
  id: string;
  title: string;
  description: string;
  status: string;
  source: string;
  /** The destination job every step leads into. */
  target: { code: string | null; title: string };
  nodes: PathViewNode[];
  edges: PathViewEdge[];
}
