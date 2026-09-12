from app.models.ai_model import AIGeneration
from app.models.ai_provider_model import AIModel, AIProvider, AITaskAssignment
from app.models.autopilot_model import AutopilotFinding, AutopilotGoal, AutopilotRun
from app.models.background_job_model import BackgroundJob
from app.models.assessment_template_model import AssessmentTemplate
from app.models.assessment_model import (
    AssessmentAnswer,
    AssessmentQuestion,
    AssessmentRun,
)
from app.models.interview_model import InterviewSession
from app.models.embedding_model import AIEmbedding
from app.models.mcp_bridge_model import AIMCPServer
from app.models.base import Base
from app.models.career_path_model import CareerPath, CareerPathStep
from app.models.chat_model import ChatMessage, ChatSession
from app.models.cv_model import CvDocument, CvVersion
from app.models.cv_synth_model import CvSynthItem  # noqa: F401
from app.models.cv_intake_model import CvParseDraft
from app.models.cv_template_model import CvTemplate
from app.models.document_model import Document
from app.models.growth_model import (
    GrowthPlan,
    GrowthPlanStep,
    LearningResource,
)
from app.models.engagement_model import (
    Notification,
    NotificationDelivery,
    NotificationKind,
    NotificationKindPref,
    NotificationPreference,
    NotificationRecipient,
    NotificationRule,
    NotificationSubscription,
    SearchHistory,
)
from app.models.profile_entities_model import (
    Certification,
    EducationItem,
    ProfileAchievement,
)
from app.models.experience_model import (
    ExperienceAchievement,
    ExperienceItem,
    ExperienceSkill,
    Organization,
    SkillEvidence,
)
from app.models.job_model import Job, JobFamily, JobRelation, JobSkill, JobTag
from app.models.matching_model import MatchInsight
from app.models.market_model import MarketSnapshot  # noqa: F401
from app.models.skill_pack_model import AISkillPack  # noqa: F401
from app.models.metric_model import (
    MetricDimension,
    SkillTransferability,
    UserMetricProfile,
)
from app.models.schedule_model import Schedule
from app.models.settings_model import AppSetting
from app.models.posting_model import (
    JobPosting,
    JobSource,
    PostingInteraction,
    PostingSkill,
)
from app.models.taxonomy_model import InterestTag, Skill
from app.models.university_model import (
    Department,
    DepartmentAdmission,
    JobDepartmentLink,
    University,
)
from app.models.user_model import Profile, User, UserInterest, UserSkill

__all__ = [
    "Base",
    "AssessmentRun",
    "AssessmentQuestion",
    "AssessmentAnswer",
    "AssessmentTemplate",
    "BackgroundJob",
    "User",
    "Profile",
    "InterestTag",
    "Skill",
    "JobFamily",
    "Job",
    "JobRelation",
    "JobSkill",
    "JobTag",
    "CareerPath",
    "CareerPathStep",
    "UserInterest",
    "UserSkill",
    "University",
    "Department",
    "DepartmentAdmission",
    "JobDepartmentLink",
    "Document",
    "CvDocument",
    "CvVersion",
    "CvTemplate",
    "CvParseDraft",
    "EducationItem",
    "Certification",
    "ProfileAchievement",
    "SearchHistory",
    "NotificationKind",
    "Notification",
    "NotificationRecipient",
    "NotificationDelivery",
    "NotificationSubscription",
    "NotificationKindPref",
    "NotificationPreference",
    "NotificationRule",
    "AppSetting",
    "Organization",
    "ExperienceItem",
    "ExperienceSkill",
    "ExperienceAchievement",
    "SkillEvidence",
    "MatchInsight",
    "MetricDimension",
    "SkillTransferability",
    "UserMetricProfile",
    "Schedule",
    "GrowthPlan",
    "GrowthPlanStep",
    "LearningResource",
    "JobSource",
    "JobPosting",
    "PostingSkill",
    "PostingInteraction",
    "ChatSession",
    "ChatMessage",
    "AIGeneration",
    "AIProvider",
    "AIModel",
    "AITaskAssignment",
    "AutopilotGoal",
    "AutopilotRun",
    "AutopilotFinding",
    "InterviewSession",
    "AIEmbedding",
    "AIMCPServer",
]
