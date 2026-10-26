/**
 * Wire types: named aliases over the generated contract
 * (`src/types/api.gen.ts`, generated from `backend/contracts/openapi.json`).
 * Hand-maintained wire shapes are gone — this file only names what the
 * contract already defines (directly, or via indexed access where the
 * schema inlines a payload). View models live in `@/types` (index).
 */

import type { components } from "@/types/api.gen";

type Schemas = components["schemas"];

// ---------------------------------------------------------------- vocab
export type DemandOutlook = Schemas["DemandOutlook"];
export type EducationLevel = Schemas["EducationLevel"];
export type Environment = Schemas["Environment"];
export type PhysicalActivity = Schemas["PhysicalActivity"];
export type RelationType = Schemas["RelationType"];
export type MatchStatus = Schemas["MatchStatus"];
export type PrerequisiteStatus = Schemas["PrerequisiteStatus"];
export type JobSkillImportance = Schemas["JobSkillImportance"];
export type JobLinkKind = Schemas["JobLinkKind"];
export type UserSkillSource = Schemas["UserSkillSource"];
export type CareerStage = Schemas["CareerStage"];
export type OnboardingPath = Schemas["OnboardingPath"];
export type SearchScope = Schemas["SearchScope"];
export type LabelEntityKind = Schemas["LabelEntityKind"];
export type NotificationRuleKind = Schemas["NotificationRuleKind"];
export type DocumentStatus = Schemas["DocumentStatus"];
export type ProfileProposalStatus = Schemas["ProfileProposalOut"]["status"];
export type ProfileLinkKind = Schemas["ProfileLink"]["kind"];
export type ExploreFacets = Schemas["ExploreOut"]["facets"];

// ---------------------------------------------------------------- catalog
export type Aspect = Schemas["Aspect"];
export type JobAttributes = Schemas["JobAttributes"];
export type Job = Schemas["JobOut"];
export type JobSkill = Schemas["JobSkillOut"];
export type InterestRef = Schemas["InterestRefOut"];
export type JobLink = Schemas["JobLink"];
export type SkillGap = Schemas["GapOut"];
export type SkillGapReport = Schemas["SkillGapReport"];
export type PathStep = Schemas["PathStepOut"];
export type CareerPath = Schemas["CareerPathOut"];
export type PathDetail = Schemas["PathDetailOut"];
export type PathGraph = Schemas["PathGraphOut"];
export type PathGraphNode = Schemas["GraphNodeOut"];
export type PathGraphEdge = Schemas["GraphEdgeOut"];
export type GraphNode = Schemas["GraphNode"];
export type GraphEdge = Schemas["GraphEdge"];
export type JobGraph = Schemas["JobGraph"];
export type Relation = Schemas["RelationOut"];
export type PrerequisiteCheck = Schemas["PrerequisiteCheck"];

// ------------------------------------------------------------- profile
export type ProfileLink = Schemas["ProfileLink"];
export type CompletenessSegment = Schemas["CompletenessSegment"];
export type CompletenessRing = Schemas["CompletenessOut"];
export type AiTaskCoverage = Schemas["AiTaskCoverageOut"];
export type AiStatus = Schemas["AiStatusOut"];
export type Bootstrap = Schemas["BootstrapOut"];
export type NotificationPreferences = Schemas["NotificationPreferencesOut"];
export type ProfileProposalDiffRow = Schemas["ProposalDiffRow"];

// ------------------------------------------------------------- matching
export type FitDimension = Schemas["FitDimension"];
export type FitBreakdown = Schemas["FitBreakdownOut"];
export type ScoringWeights = Schemas["ScoringWeights"];
export type MatchInsight = Schemas["MatchInsightOut"];
export type RankedJob = Schemas["RankedJob"];
export type Candidate = Schemas["CandidateOut"];

// ---------------------------------------------------------- universities
export type DegreeLevel = Schemas["DegreeLevel"];
export type UniversityType = Schemas["UniversityType"];
export type PostingExtractSkillOut = Schemas["PostingExtractSkillOut"];
export type University = Schemas["UniversityOut"];
export type Admission = Schemas["AdmissionOut"];
export type JobDepartmentLink = Schemas["JobDepartmentLinkOut"];
export type Department = Schemas["DepartmentOut"];
export type UniversityDetail = Schemas["UniversityDetailOut"];

// ---------------------------------------------------------------- companies
export type Company = Schemas["CompanyOut"];
export type CompanyDetail = Schemas["CompanyDetailOut"];
export type CompanyPosting = Schemas["CompanyPostingOut"];

// ---------------------------------------------------------------- job radar
export type RadarOut = Schemas["RadarOut"];

// ----------------------------------------------------------------- chat
export type ChatSession = Schemas["SessionOut"];

// ------------------------------------------------- documents and feeds
export type FeedItem = Schemas["FeedItemOut"];
export type FeedResponse = Schemas["FeedOut"];
export type SearchRecord = Schemas["SearchOut"];

// ------------------------------------------------------- notifications
export type AlertRuleParams = Schemas["RuleParams"];
export type AlertRule = Schemas["RuleOut"];
export type NotificationsResponse = Schemas["NotificationsOut"];
export type NotificationKindPref = Schemas["KindPrefOut"];
export type PreferencesMatrix = Schemas["PreferencesMatrixOut"];
export type NotificationItem = Schemas["NotificationOut"];
export type NotificationThread = Schemas["ThreadOut"];
export type ThreadsResponse = Schemas["ThreadsOut"];
export type PushSubscriptionRecord = Schemas["SubscriptionOut"];
export type EmailChannelConfig = Schemas["EmailChannelConfigOut"];
export type WebhookChannelConfig = Schemas["WebhookChannelConfigOut"];
export type ChannelTestResult = Schemas["ChannelTestOut"];
export type FeedToken = Schemas["FeedTokenOut"];
export type FeedTokenMinted = Schemas["FeedTokenMintedOut"];
export type EmailTransportConfig = Schemas["EmailTransportOut"];

// ------------------------------------------------------------- postings
export type PostingOut = Schemas["PostingOut"];
export type PostingDetailSkill = Schemas["PostingExtractSkillOut"];
export type PostingDetailOut = Schemas["PostingDetailOut"];
export type PostingsResponse = Schemas["PostingsOut"];
export type ExploreResponse = Schemas["ExploreOut"];
export type ResolveArchetype = Schemas["ArchetypeOut"];
export type ResolveResponse = Schemas["ResolveOut"];
export type ExpressStart = Schemas["ExpressIn"];
export type ExpressResult = Schemas["ExpressOut"];
export type Nudge = Schemas["NudgeOut"];
export type PostingSourceInfo = {
  key: string;
  connector_key: string;
  open_postings: number;
};

// --------------------------------------------------- growth and admin
export type TargetDashboard = Schemas["TargetDashboardOut"];
export type GrowthStep = Schemas["GrowthStepOut"];
export type GrowthPlanItem = Schemas["GrowthPlanOut"];
export type RadarEntry = Schemas["RadarEntryOut"];
export type MarketSnapshot = Schemas["MarketSnapshotOut"];
export type CheckinStatus = Schemas["CheckinStatusOut"];
export type ScheduleItem = Schemas["ScheduleItemOut"];
export type LocaleState = Schemas["MeLocaleStateOut"];
export type LabelOverlay = Schemas["OverlayOut"];
export type OverlayDraftResult = Schemas["OverlayDraftResultOut"];
