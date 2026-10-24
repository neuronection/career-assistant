"""Controlled vocabularies: interest tags + skill tags (stable keys).

Plan 123.5: the literals live in ``app/data/seeds/taxonomy.json``,
pydantic-validated at load (see ``app/seeds/data.py``).
"""

from app.seeds.data import InterestTag, SkillTag, seed_list

INTEREST_TAGS: list[dict] = seed_list(InterestTag, "taxonomy", "INTEREST_TAGS")

SKILL_TAGS: list[dict] = seed_list(SkillTag, "taxonomy", "SKILL_TAGS")
