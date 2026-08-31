from fastapi import APIRouter

from app.api.v1 import (
    admin,
    assessments,
    ai_admin,
    auth,
    background_jobs,
    chat,
    documents,
    engagement,
    growth,
    jobs,
    matching,
    me,
    onboarding,
    paths,
    postings,
    scheduler,
    profile,
    skills,
    taxonomy,
    universities,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(me.router)
api_router.include_router(onboarding.router)
api_router.include_router(profile.router)
api_router.include_router(taxonomy.router)
api_router.include_router(assessments.router)
api_router.include_router(skills.router)
api_router.include_router(paths.router)
api_router.include_router(jobs.router)
api_router.include_router(universities.router)
api_router.include_router(documents.router)
api_router.include_router(matching.router)
api_router.include_router(engagement.router)
api_router.include_router(growth.router)
api_router.include_router(postings.router)
api_router.include_router(scheduler.router)
api_router.include_router(chat.router)
api_router.include_router(background_jobs.router)
api_router.include_router(ai_admin.router)
api_router.include_router(admin.router)
