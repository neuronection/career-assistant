export type ApplicationStage =
  | "applied"
  | "screening"
  | "interview"
  | "offer"
  | "accepted"
  | "rejected"
  | "withdrawn";

export type ApplicationOutcome =
  | "accepted"
  | "rejected"
  | "withdrawn"
  | "expired"
  | "ghosted";

export type ApplicationVia =
  | "url"
  | "email"
  | "portal"
  | "referral"
  | "event"
  | "other";

export interface ApplicationEvent {
  id: string;
  at: string;
  kind: string;
  stage_from: string | null;
  stage_to: string | null;
  body: string;
  actor: string;
  meta: Record<string, unknown>;
}

export type OfferPeriod = "year" | "month" | "hour";

export interface ApplicationOffer {
  currency: string;
  amount: number;
  period: OfferPeriod;
  benefits: string[];
  location: string;
  cost_of_living: number | null;
  deadline: string | null;
}

export interface OfferComparisonItem extends ApplicationOffer {
  application_id: string;
  posting_title: string;
  posting_org: string;
  annual_amount: number;
  monthly_amount: number;
  annual_cost_of_living: number | null;
  net_annual_after_col: number | null;
}

export interface OfferComparison {
  items: OfferComparisonItem[];
  total: number;
  mixed_currencies: boolean;
}

export interface Application {
  id: string;
  posting_id: string;
  posting_ref: string;
  posting_title: string;
  posting_org: string;
  stage: ApplicationStage;
  applied_at: string | null;
  applied_via: ApplicationVia;
  applied_via_url: string;
  deadline_at: string | null;
  next_followup_at: string | null;
  contact_id: string | null;
  offer: Partial<ApplicationOffer>;
  outcome: ApplicationOutcome | null;
  closed_at: string | null;
  cv_id: string | null;
  cover_letter_id: string | null;
  external_ref: string;
  notes: string;
  meta: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ApplicationDetail extends Application {
  timeline: ApplicationEvent[];
}

export interface ApplicationFunnel {
  saved: number;
  applied: number;
  interviewing: number;
  offers: number;
  closed: number;
}

export interface ApplicationList {
  items: Application[];
  total: number;
  funnel: ApplicationFunnel;
  next_followup_at: string | null;
}

export interface FollowupRules {
  enabled: boolean;
  cadence_days: number[];
  milestone_checkins: boolean;
  channels: Record<string, string[]>;
}

export interface FollowupItem {
  application_id: string;
  posting_ref: string | null;
  role: string;
  org: string;
  applied_at: string;
  stage: ApplicationStage;
  sent_steps: string[];
  next_step: string | null;
  next_due: string | null;
  due_now: boolean;
}

export interface FollowupSurface {
  rules: FollowupRules;
  items: FollowupItem[];
}
