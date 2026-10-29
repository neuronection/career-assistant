from fastapi import APIRouter

from app.api.v1 import (
    admin,
    ai,
    ai_admin,
    assessments,
    audit,
    autopilot,
    background_jobs,
    cv_intake,
    cv_templates,
    github_intake,
    growth,
    instance,
    mcp_admin,
    me,
    metrics,
    profiles,
    scheduler,
    skill_relation_admin,
)
from app.api.v1.catalog import companies as companies
from app.api.v1.catalog import jobs as jobs
from app.api.v1.catalog import matching as matching
from app.api.v1.catalog import paths as paths
from app.api.v1.catalog import skills as skills
from app.api.v1.catalog import taxonomy as taxonomy
from app.api.v1.catalog import universities as universities
from app.api.v1.chat import chat as chat
from app.api.v1.chat import interview as interview
from app.api.v1.cv import cv_synth as cv_synth
from app.api.v1.cv import cvs as cvs
from app.api.v1.integrations import extensions as extensions
from app.api.v1.integrations import feeds as feeds
from app.api.v1.postings import applications as applications
from app.api.v1.postings import engagement as engagement
from app.api.v1.postings import history as history
from app.api.v1.postings import postings as postings
from app.api.v1.profile import documents as documents
from app.api.v1.profile import experience as experience
from app.api.v1.profile import me_cv_data as me_cv_data
from app.api.v1.profile import me_photo as me_photo
from app.api.v1.profile import notifications as notifications
from app.api.v1.profile import onboarding as onboarding
from app.api.v1.profile import profile as profile
from app.api.v1.profile import profile_proposals as profile_proposals

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(instance.router)
api_router.include_router(autopilot.router)
api_router.include_router(me.router)
api_router.include_router(applications.router)
api_router.include_router(me_cv_data.router)
api_router.include_router(me_photo.router)
api_router.include_router(metrics.router)
api_router.include_router(onboarding.router)
api_router.include_router(profile.router)
api_router.include_router(profiles.router)
api_router.include_router(taxonomy.router)
api_router.include_router(assessments.router)
api_router.include_router(skills.router)
api_router.include_router(paths.router)
api_router.include_router(jobs.router)
api_router.include_router(companies.router)
api_router.include_router(universities.router)
api_router.include_router(documents.router)
api_router.include_router(cv_templates.router)
api_router.include_router(cv_intake.router)
api_router.include_router(github_intake.router)
api_router.include_router(cv_synth.router)
api_router.include_router(cvs.router)
api_router.include_router(matching.router)
api_router.include_router(engagement.router)
api_router.include_router(experience.router)
api_router.include_router(profile_proposals.router)
api_router.include_router(notifications.router)
api_router.include_router(feeds.router)
api_router.include_router(growth.router)
api_router.include_router(postings.router)
api_router.include_router(history.router)
api_router.include_router(scheduler.router)
api_router.include_router(chat.router)
api_router.include_router(interview.router)
api_router.include_router(background_jobs.router)
api_router.include_router(ai.router)
api_router.include_router(ai_admin.router)
api_router.include_router(mcp_admin.router)
api_router.include_router(admin.router)
api_router.include_router(audit.router)
api_router.include_router(skill_relation_admin.router)
api_router.include_router(extensions.router)
