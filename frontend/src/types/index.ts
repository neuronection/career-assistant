export type DemandOutlook = "declining" | "stable" | "growing" | "hot";
export type EducationLevel =
  | "no_formal"
  | "middle_school"
  | "high_school"
  | "vocational"
  | "bachelor"
  | "master"
  | "doctorate";
export type Environment =
  | "office"
  | "field"
  | "lab"
  | "studio"
  | "workshop"
  | "clinic"
  | "classroom"
  | "vehicle"
  | "outdoors"
  | "remote"
  | "kitchen"
  | "stage";
export type PhysicalActivity = "sedentary" | "light" | "moderate" | "active" | "physical_intense";
export type RelationType =
  | "similar_to"
  | "specialises_into"
  | "leads_to"
  | "alternative_to"
  | "prerequisite_of";
export type MatchStatus = "interested" | "considering" | "dismissed";
export type PrerequisiteStatus = "met" | "unmet" | "unknown";

export interface Aspect {
  title: string;
  detail: string;
  weight?: number;
}

export interface JobAttributes {
  subjects: string[];
  work_style: {
    teamwork: number;
    environment: number;
    structure: number;
    pace: number;
    leadership: number;
    physical_activity: PhysicalActivity;
  };
  education: { level: EducationLevel; fields: string[] };
  physical: { activity: PhysicalActivity; requirements: string[] };
  salary: {
    currency: string;
    entry: [number, number] | null;
    median: [number, number] | null;
    senior: [number, number] | null;
  };
  demand: { outlook: DemandOutlook; note: string; sources: Record<string, unknown> };
  environments: Environment[];
  typical_positives: Aspect[];
  typical_negatives: Aspect[];
}

export type JobSkillImportance = "core" | "important" | "bonus";

export interface JobSkill {
  skill_id: string;
  key: string;
  label: string;
  required_level: number;
  importance: JobSkillImportance;
  rationale: string;
}

export interface InterestRef {
  key: string;
  label: string;
}

export interface Job {
  id: string;
  code: string;
  title: string;
  family_key: string;
  short_description: string;
  status: "draft" | "published";
  source: "seed" | "ai" | "user";
  attributes: JobAttributes;
  interests: InterestRef[];
  skills: JobSkill[];
  links?: JobLink[];
  created_at: string;
}

export type JobLinkKind = "apply" | "learn" | "certification" | "video";

export interface JobLink {
  label: string;
  url: string;
  kind: JobLinkKind;
}

export type SkillStatus = "proposed" | "active" | "deprecated";

export interface LevelAnchor {
  level: number;
  label: string;
  description: string;
}

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

export type UserSkillSource =
  | "self_report"
  | "assessment"
  | "experience"
  | "ai_inferred"
  | "document";

export interface UserSkill {
  skill_id: string;
  key: string;
  label: string;
  category: string;
  level: number;
  source: UserSkillSource;
  confidence: number;
  level_anchors: LevelAnchor[];
}

export interface SkillGap {
  skill_id: string;
  key: string;
  label: string;
  required_level: number;
  importance: JobSkillImportance;
  user_level: number | null;
  delta: number | null;
  suggestion: string;
  next_step: string | null;
}

export interface SkillGapReport {
  job_id: string;
  job_code: string;
  job_title: string;
  gaps: SkillGap[];
}

export interface PathStep {
  position: number;
  kind: "education" | "job" | "experience" | "certification";
  label: string;
  optional: boolean;
  family_key: string | null;
  family_label: string | null;
  skill_key: string | null;
  skill_label: string | null;
  education_level: string | null;
}

export interface CareerPath {
  id: string;
  job_id: string;
  title: string;
  description: string;
  source: string;
  status: string;
  steps: PathStep[];
}

export interface PathGraphNode {
  code: string;
  title: string;
  family_key: string;
  demand: string | null;
  depth: number;
}

export interface PathGraphEdge {
  from_code: string;
  to_code: string;
  relation_type: string;
  weight: number;
}

export interface PathGraph {
  root: string;
  nodes: PathGraphNode[];
  edges: PathGraphEdge[];
  truncated: boolean;
}

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

export interface GraphNode {
  id: string;
  code: string;
  title: string;
  family_key: string;
  demand: string | null;
}

export interface GraphEdge {
  from_code: string;
  to_code: string;
  relation_type: RelationType;
  weight: number;
}

export interface JobGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Relation {
  id: string;
  from_code: string;
  to_code: string;
  from_title: string;
  to_title: string;
  relation_type: RelationType;
  weight: number;
  rationale: string;
  source: string;
}

export interface TaxonomyTag {
  key: string;
  label: string;
  category: string;
  description: string;
}

export type CareerStage =
  | "student"
  | "early_career"
  | "experienced"
  | "switching"
  | "returning";

export interface Profile {
  basics: {
    birth_year: number | null;
    education_level: EducationLevel;
    grade: string | null;
    career_stage?: CareerStage | null;
    country: string;
    city: string;
  };
  academics: {
    favorite_subjects: { key: string; weight: number }[];
    gpa_band?: string | null;
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
  experience: {
    title: string;
    org: string;
    kind: "internship" | "part_time" | "volunteer" | "project" | "freelance";
    start_year: number;
    end_year: number | null;
    hours_per_week: number | null;
    skill_keys: string[];
    description: string;
  }[];
  preferences: {
    scoring_weights: {
      skills: number;
      location: number;
      experience: number;
      education: number;
      interests: number;
    };
  };
  constraints: {
    physical_conditions: string[];
    max_education_years: number | null;
    willing_to_relocate: boolean;
    hours_available_per_week: number | null;
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
  completeness: { percent: number; sections: Record<string, boolean> };
}

export interface Bootstrap {
  career_stage: CareerStage;
  stage_source: "derived" | "explicit";
  features: { universities: boolean; grade_fields: boolean };
  suggested_scoring_weights: ScoringWeights;
  effective_scoring_weights: ScoringWeights;
  weights_overridden: boolean;
  refitted?: number;
  target_mode?: boolean;
  target_families?: string[];
  notification_channels?: NotificationChannel[];
}

export type NotificationChannel = "in_app" | "desktop" | "browser";

export interface NotificationPreferences {
  desktop_channel_enabled: boolean;
  quiet_hours: { start: string; end: string } | null;
}

export interface PrerequisiteCheck {
  requirement: string;
  status: PrerequisiteStatus;
  detail: string;
}

export interface FitDimension {
  score: number;
  weight: number;
  detail: string;
}

export interface FitBreakdown {
  dimensions: Record<string, FitDimension>;
  gates: string[];
  specialist_dimension: string | null;
}

export interface ScoringWeights {
  skills: number;
  location: number;
  experience: number;
  education: number;
  interests: number;
}

export interface MatchInsight {
  id: string;
  job_id: string;
  ai_score: number | null;
  ai_confidence: number | null;
  ai_summary: string;
  ai_positives: Aspect[];
  ai_negatives: Aspect[];
  prerequisites: PrerequisiteCheck[];
  ai_model: string;
  ai_generated_at: string | null;
  fit_score: number | null;
  fit_breakdown: FitBreakdown | null;
  fit_version: number;
  user_score: number | null;
  status: MatchStatus | null;
  user_notes: string;
  seen_at: string | null;
  saved_at: string | null;
  hidden_at: string | null;
}

export interface RankedJob {
  job: Job;
  score: number;
  fit_score: number;
  ai_score: number | null;
  user_score: number | null;
  status: MatchStatus | null;
  breakdown: FitBreakdown | null;
  specialist_dimension: string | null;
  gated: boolean;
  gate_reasons: string[];
  insight: MatchInsight | null;
}

export interface Candidate {
  job: Job;
  fit_score: number;
  breakdown: FitBreakdown | null;
}

export interface University {
  id: string;
  name: string;
  country: string;
  city: string;
  university_type: string;
  website: string;
  notes: string;
  source: string;
  department_count: number;
}

export interface Admission {
  id: string;
  year: number;
  baseline_score: number | null;
  top_score: number | null;
  quota: number | null;
  units: string;
  source: string;
  confidence: number;
}

export interface JobDepartmentLink {
  id: string;
  job_id: string;
  department_id: string;
  relevance: number;
  rationale: string;
  required_subjects: string[];
  typical_position: string;
  salary_band: Record<string, unknown> | null;
  employment_rate_pct: number | null;
  source: string;
}

export interface Department {
  id: string;
  university_id: string;
  name: string;
  field_key: string;
  degree: string;
  duration_years: number;
  language: string;
  application_deadline: string | null;
  description: string;
  admissions: Admission[];
  job_links: JobDepartmentLink[];
}

export interface UniversityDetail extends University {
  departments: Department[];
}

export interface DocumentRecord {
  id: string;
  kind: string;
  filename: string;
  mime: string;
  size_bytes: number;
  page_count: number;
  status: "uploaded" | "parsing" | "parsed" | "error" | "applied";
  error: string;
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

export interface ChatSession {
  id: string;
  title: string;
  context: Record<string, unknown> | null;
  created_at: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  metadata_json: {
    referenced_job_codes?: string[];
    referenced_posting_refs?: string[];
    explore_query?: string;
    tools?: { name: string; results: string[] }[];
  } | null;
  created_at: string;
}

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

export type SearchScope = "catalog" | "rankings" | "universities" | "postings";

export interface SearchRecord {
  id: string;
  scope: SearchScope;
  query: string;
  filters: Record<string, unknown>;
  result_count: number;
  saved: boolean;
  created_at: string;
}

export interface FeedItem {
  job: Job;
  fit_score: number;
  insight: MatchInsight | null;
  seen: boolean;
  saved: boolean;
  user_notes: string;
  exploration: boolean;
}

export interface FeedResponse {
  items: FeedItem[];
  total: number;
  unseen: number;
}

export type AlertRuleKind = "fit_threshold" | "new_in_family";

export interface AlertRuleParams {
  min_fit: number;
  family_keys: string[];
  muted_family_keys: string[];
  max_per_day: number;
}

export interface AlertRule {
  kind: AlertRuleKind;
  params: AlertRuleParams;
  enabled: boolean;
  is_default: boolean;
}

export interface NotificationItem {
  id: string;
  notification_id: string;
  kind: string;
  severity: "info" | "success" | "warning" | "critical";
  status: "unread" | "read" | "dismissed";
  title: string;
  body: string;
  payload: {
    job_id?: string;
    job_code?: string;
    family_key?: string;
    score?: number;
    link?: string;
    [key: string]: unknown;
  };
  source_ref: Record<string, string>;
  thread_key: string | null;
  read_at: string | null;
  dismissed_at: string | null;
  created_at: string;
}

export interface NotificationsResponse {
  items: NotificationItem[];
  unread_count: number;
}

export interface NotificationThread {
  thread_key: string;
  kind: string;
  severity: "info" | "success" | "warning" | "critical";
  title: string;
  payload: NotificationItem["payload"];
  source_ref: Record<string, string>;
  unread_count: number;
  items: NotificationItem[];
  created_at: string;
}

export interface ThreadsResponse {
  threads: NotificationThread[];
  unread_count: number;
}

export interface NotificationKindPref {
  key: string;
  label: string;
  group: string;
  severity: "info" | "success" | "warning" | "critical";
  manage_url: string | null;
  mutable: boolean;
  default_channels: NotificationChannelKey[];
  enabled: boolean;
  channels: NotificationChannelKey[];
  overridden: boolean;
}

export type NotificationChannelKey = "in_app" | "desktop" | "browser";

export interface PreferencesMatrix {
  channels: NotificationChannelKey[];
  quiet_hours: { start: string; end: string } | null;
  desktop_channel_enabled: boolean;
  kinds: NotificationKindPref[];
}

export interface PushSubscriptionRecord {
  device_id: string;
  is_active: boolean;
  created_at: string;
}

export interface NotificationPreferences {
  desktop_channel_enabled: boolean;
  quiet_hours: { start: string; end: string } | null;
}

export interface PostingMatchBreakdown {
  score: number;
  weight: number;
  detail: string;
  neutral?: boolean;
}

export interface PostingMatch {
  score: number;
  breakdown: Record<string, PostingMatchBreakdown>;
  extracted: boolean;
  estimate: boolean;
  inputs_hash: string;
}

export interface PostingSimilar {
  ref: string;
  title: string;
  org: string;
  score: number;
}

export type ExploreFacets = Record<string, Record<string, number>>;

export interface ExploreResponse {
  items: JobPostingItem[];
  total: number;
  next_cursor: string | null;
  facets: ExploreFacets;
}

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
  sort?: string;
  cursor?: string;
  limit?: number;
}

export interface PostingSourceInfo {
  key: string;
  connector_key: string;
  open_postings: number;
}

export type PostingSeniority = "intern" | "junior" | "mid" | "senior" | "lead" | "principal";

export type PostingSkillPriority = "must_have" | "nice_to_have" | "bonus";

export interface PostingExtractSkill {
  skill_key?: string | null;
  raw_label?: string | null;
  unresolved?: boolean;
  required_level: number;
  priority: PostingSkillPriority;
  evidence_quote: string;
  confidence: number;
}

export interface PostingExtractResponsibility {
  text: string;
  time_pct?: number | null;
  optional?: boolean;
}

export interface PostingExtract {
  title_norm?: string | null;
  seniority?: string | null;
  employment_type?: string | null;
  remote_policy?: string | null;
  location?: { city?: string | null; country?: string | null } | null;
  salary?: {
    min?: number | null;
    max?: number | null;
    currency?: string | null;
    period?: string | null;
  } | null;
  education?: { level?: string | null; field?: string | null } | null;
  languages?: string[];
  benefits?: string[];
  responsibilities?: PostingExtractResponsibility[];
  skills?: PostingExtractSkill[];
  field_confidence?: Record<string, number>;
  _suppressed_fields?: string[];
}

export interface JobPostingItem {
  id: string;
  ref?: string;
  source_id: string;
  external_id: string;
  title: string;
  org: string;
  location: { city?: string | null; country?: string | null; remote?: boolean };
  url: string;
  seniority?: PostingSeniority | null;
  employment_type?: string | null;
  onsite_policy?: string | null;
  salary_currency?: string | null;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_period?: string | null;
  posted_at?: string | null;
  expires_at?: string | null;
  status: "new" | "mapped" | "expired" | "hidden";
  catalog_job_id?: string | null;
  mapping_method?: string | null;
  mapping_confidence?: number | null;
  mapping_reason?: string;
  fit?: number | null;
  seen: boolean;
  saved: boolean;
  applied_at?: string | null;
  notes?: string;
  source_key: string;
  extract_version?: number | null;
  needs_review?: boolean;
  coverage?: number | null;
  extract?: PostingExtract | null;
  // Detail-only fields (GET /postings/{ref}):
  source_title?: string;
  source_connector?: string;
  source_synced_at?: string | null;
  match?: PostingMatch | null;
  similar?: PostingSimilar[];
}

export interface PostingsResponse {
  items: JobPostingItem[];
  total: number;
  unseen: number;
}

export interface ResolveArchetype {
  code: string;
  title: string;
  family_key: string;
  score: number;
}

export interface ResolveResponse {
  query: string;
  resolved_by: string;
  families: { key: string; label: string }[];
  skill_keys: string[];
  archetypes: ResolveArchetype[];
}

export interface ExpressStart {
  targets: string[];
  location?: string;
  remote?: boolean;
  stage?: string;
  min_fit?: number;
  max_per_day?: number;
}

export interface ExpressResult {
  target_families: string[];
  target_labels: string[];
  interest_tags_written: number;
  target_mode: boolean;
}

export interface CompletenessSegment {
  key: string;
  label: string;
  filled: boolean;
  hint: string;
  href: string;
}

export interface CompletenessRing {
  percent: number;
  segments: CompletenessSegment[];
}

export interface Nudge {
  type: string;
  message: string;
}

export interface TargetDashboard {
  families: string[];
  open_postings: {
    total: number;
    unseen: number;
    salary_band: { min: number | null; max: number | null };
    top_employers: { org: string; count: number }[];
  };
  adjacent_targets: { family_key: string; label: string; sample: string }[];
  nudges: Nudge[];
  completeness: CompletenessRing;
}

export interface GrowthStep {
  id: string;
  position: number;
  kind: string;
  label: string;
  skill_id?: string | null;
  target_level?: number | null;
  status: "todo" | "doing" | "done" | "skipped";
  completed_level?: number | null;
  resources: { id: string; kind: string; title: string; provider: string; url: string; cost: string }[];
}

export interface GrowthPlanItem {
  id: string;
  status: string;
  target_job: { id: string; title: string; code: string };
  completed_at?: string | null;
  steps: GrowthStep[];
}

export interface RadarEntry {
  job_id: string;
  code: string;
  title: string;
  family_key: string;
  fit_score: number;
  deficits: {
    skill_id: string;
    key: string;
    label: string;
    current_level: number;
    required_level: number;
    delta: number;
    importance: string;
  }[];
  headline: string;
}

export interface MarketSnapshot {
  sample_size: number;
  thin_sample: boolean;
  months: { month: string; postings: number }[];
  salary_band: { p25: number | null; p75: number | null } | null;
  top_employers: { org: string; count: number }[];
  top_skills: { key: string; count: number }[];
}

export interface CheckinStatus {
  due: boolean;
  next_at: string;
  last_at?: string | null;
}

export interface ScheduleItem {
  id: string;
  kind: string;
  task?: string | null;
  trigger: { type: string; params: Record<string, unknown> };
  payload: Record<string, unknown>;
  enabled: boolean;
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_status?: string | null;
  consecutive_failures?: number;
  misfire_policy?: string;
  error?: string;
  removed?: boolean;
}
