"""Evidence-derived NACE competencies (plan 212 S3.5).

Every competency is computed from the user's own recorded evidence —
experience title/description, achievements, linked skills and
certifications. There is no self-rating, no level and no score: a
competency either cites evidence or says there is none.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.experience_model import ExperienceItem, ExperienceSkill
from app.models.profile_entities_model import Certification
from app.models.user_model import UserSkill

MAX_EVIDENCE = 4

# NACE career-readiness competencies, in the framework's stable order.
# Terms are exact normalized words/phrases (with common inflections), never
# substrings: "led" must not match "ledger", "language" must not match
# "programming language".
COMPETENCIES: dict[str, tuple[str, ...]] = {
    "critical_thinking": (
        "analyze",
        "analyzed",
        "analyzes",
        "analyzing",
        "analysis",
        "research",
        "researched",
        "problem",
        "problems",
        "evaluate",
        "evaluated",
        "evaluates",
        "evaluating",
        "evaluation",
        "diagnose",
        "diagnosed",
        "investigate",
        "investigated",
        "investigation",
        "experiment",
        "experiments",
        "optimize",
        "optimized",
        "optimization",
        "strategy",
        "strategic",
        "decision",
        "decisions",
        "ανάλυση",
        "έρευνα",
        "πρόβλημα",
    ),
    "communication": (
        "write",
        "writes",
        "wrote",
        "written",
        "writing",
        "present",
        "presented",
        "presenting",
        "presentation",
        "report",
        "reports",
        "reported",
        "document",
        "documents",
        "documented",
        "documentation",
        "communicate",
        "communicated",
        "communication",
        "stakeholder",
        "stakeholders",
        "publish",
        "published",
        "edit",
        "edited",
        "editing",
        "translate",
        "translated",
        "translation",
        "kommunikation",
        "επικοινωνία",
        "παρουσίαση",
    ),
    "teamwork": (
        "team",
        "teams",
        "teamwork",
        "collaborate",
        "collaborated",
        "collaboration",
        "cross functional",
        "partner",
        "partners",
        "partnership",
        "coordinate",
        "coordinated",
        "coordination",
        "volunteer",
        "volunteers",
        "volunteering",
        "group",
        "groups",
        "ομάδα",
        "ομάδες",
        "συνεργασία",
        "ομαδικός",
        "ομαδική",
    ),
    "digital_technology": (
        "software",
        "python",
        "sql",
        "cloud",
        "data",
        "database",
        "databases",
        "code",
        "coding",
        "develop",
        "developed",
        "developer",
        "development",
        "automate",
        "automated",
        "automation",
        "technical",
        "technology",
        "analytics",
        "machine learning",
        "artificial intelligence",
        "ψηφιακός",
        "ψηφιακή",
        "δεδομένα",
        "προγραμματισμός",
    ),
    "leadership": (
        "led",
        "lead",
        "leads",
        "leading",
        "manage",
        "managed",
        "manager",
        "managers",
        "management",
        "managing",
        "mentor",
        "mentored",
        "mentoring",
        "supervise",
        "supervised",
        "supervisor",
        "chair",
        "chaired",
        "founder",
        "founded",
        "captain",
        "coach",
        "coached",
        "ηγεσία",
        "διεύθυνση",
        "μέντορας",
    ),
    "professionalism": (
        "deadline",
        "deadlines",
        "quality",
        "compliance",
        "compliant",
        "audit",
        "audited",
        "reliable",
        "reliability",
        "deliver",
        "delivered",
        "delivery",
        "process",
        "processes",
        "safety",
        "accuracy",
        "accurate",
        "on time",
        "ποιότητα",
        "αξιοπιστία",
        "παράδοση",
    ),
    "career_management": (
        "career",
        "careers",
        "goal",
        "goals",
        "certificate",
        "certificates",
        "certification",
        "certifications",
        "certified",
        "course",
        "courses",
        "training",
        "trained",
        "portfolio",
        "feedback",
        "continuous learning",
        "learning plan",
        "learning goal",
        "σταδιοδρομία",
        "στόχος",
        "στόχοι",
        "κατάρτιση",
        "μάθηση",
    ),
    "intercultural": (
        "foreign language",
        "foreign languages",
        "second language",
        "international",
        "global",
        "globally",
        "diverse",
        "diversity",
        "multilingual",
        "bilingual",
        "abroad",
        "cross cultural",
        "intercultural",
        "cultural fluency",
        "ξένη γλώσσα",
        "διεθνής",
        "πολυπολιτισμικός",
    ),
}


def _normalise(value: str) -> str:
    return " ".join(re.sub(r"[_\W]+", " ", (value or "").lower()).split())


def competency_keys_for_text(text: str) -> list[str]:
    """The competency keys whose exact terms occur in one piece of evidence."""
    corpus = _normalise(text)
    if not corpus:
        return []
    keys: list[str] = []
    for key, terms in COMPETENCIES.items():
        for raw in terms:
            term = _normalise(raw)
            if term and re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", corpus):
                keys.append(key)
                break
    return keys


async def user_competencies(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    """All eight competencies with up to four deterministic evidence rows."""
    evidence: dict[str, list[dict]] = {key: [] for key in COMPETENCIES}
    seen: dict[str, set[str]] = {key: set() for key in COMPETENCIES}

    def add(key: str, row: dict) -> None:
        if row["id"] in seen[key] or len(evidence[key]) >= MAX_EVIDENCE:
            return
        evidence[key].append(row)
        seen[key].add(row["id"])

    experiences = (
        (
            await db.execute(
                select(ExperienceItem)
                .options(
                    selectinload(ExperienceItem.skills).selectinload(ExperienceSkill.skill),
                    selectinload(ExperienceItem.achievements),
                )
                .where(
                    ExperienceItem.user_id == user_id,
                    ExperienceItem.status == "active",
                )
                .order_by(
                    ExperienceItem.start.desc().nulls_last(),
                    ExperienceItem.created_at.desc(),
                    ExperienceItem.id,
                )
            )
        )
        .scalars()
        .all()
    )

    for item in experiences:
        experience_id = f"experience:{item.id}"
        for key in competency_keys_for_text(item.title):
            add(
                key,
                {
                    "id": experience_id,
                    "kind": "experience",
                    "label": item.title,
                    "quote": item.title,
                },
            )
        for key in competency_keys_for_text(item.description):
            add(
                key,
                {
                    "id": experience_id,
                    "kind": "experience",
                    "label": item.title,
                    "quote": item.description.strip()[:180],
                },
            )
        for achievement in sorted(item.achievements, key=lambda row: row.id):
            for key in competency_keys_for_text(achievement.text):
                add(
                    key,
                    {
                        "id": f"achievement:{achievement.id}",
                        "kind": "achievement",
                        "label": item.title,
                        "quote": achievement.text[:180],
                    },
                )
        for link in sorted(
            item.skills,
            key=lambda row: (
                (row.skill.label if row.skill is not None else "").lower(),
                str(row.skill_id),
            ),
        ):
            if link.skill is None:
                continue
            for key in competency_keys_for_text(link.skill.label):
                add(
                    key,
                    {
                        "id": f"skill:{link.skill.id}",
                        "kind": "skill",
                        "label": link.skill.label,
                        "quote": "",
                    },
                )

    certifications = (
        (
            await db.execute(
                select(Certification)
                .where(
                    Certification.user_id == user_id,
                    Certification.status == "active",
                )
                .order_by(
                    Certification.issued.desc().nulls_last(),
                    Certification.created_at.desc(),
                    Certification.id,
                )
            )
        )
        .scalars()
        .all()
    )
    for cert in certifications:
        for key in competency_keys_for_text(cert.name):
            add(
                key,
                {
                    "id": f"certification:{cert.id}",
                    "kind": "certification",
                    "label": cert.name,
                    "quote": "",
                },
            )

    user_skills = (
        (
            await db.execute(
                select(UserSkill)
                .options(selectinload(UserSkill.skill))
                .where(
                    UserSkill.user_id == user_id,
                    UserSkill.hidden.is_(False),
                )
                .order_by(UserSkill.created_at.desc(), UserSkill.id)
            )
        )
        .scalars()
        .all()
    )
    for claimed in user_skills:
        if claimed.skill is None:
            continue
        for key in competency_keys_for_text(claimed.skill.label):
            add(
                key,
                {
                    "id": f"skill:{claimed.skill.id}",
                    "kind": "skill",
                    "label": claimed.skill.label,
                    "quote": "",
                },
            )

    return [{"key": key, "evidence": evidence[key]} for key in COMPETENCIES]
