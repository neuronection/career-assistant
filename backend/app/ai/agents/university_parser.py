from app.models.enums import AITaskType
from app.ai.agents.context import context_json, parse_context
from app.ai.provider import ainvoke_structured, register_mock_fixture
from app.ai.schemas import UniversityExtraction
from sqlalchemy.ext.asyncio import AsyncSession


def _build_user_prompt(text: str, max_chars: int = 24000) -> str:
    clipped = text[:max_chars]
    return context_json({"document_text": clipped})


def _normalise_deadline(raw: str | None) -> str | None:
    """Normalise a deadline string to ISO yyyy-mm-dd (or None)."""
    if not raw:
        return None
    import re
    from datetime import date

    text = raw.strip()
    iso = re.fullmatch(r"(20\d{2})-(\d{2})-(\d{2})", text)
    if iso:
        try:
            date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
            return text
        except ValueError:
            return None
    eu = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](20\d{2})", text)
    if eu:
        day, month, year = int(eu.group(1)), int(eu.group(2)), int(eu.group(3))
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None
    return None


def _mock_extraction(schema: type, user_prompt: str) -> dict:
    ctx = parse_context(user_prompt)
    text = ctx.get("document_text", "")
    import re

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    uni_name = next(
        (line for line in lines if "university" in line.lower()),
        "University of the Mock Text",
    )
    uni_name = uni_name.strip("-—:").strip()
    deadline_match = re.search(
        r"(?:deadline|apply by|applications? (?:close|due))\s*[:\-]?\s*"
        r"(\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{4})",
        text,
        re.IGNORECASE,
    )
    deadline = _normalise_deadline(deadline_match.group(1) if deadline_match else None)
    departments = []
    for line in lines:
        lower = line.lower()
        marker = (
            "school of"
            if "school of" in lower
            else ("faculty of" if "faculty of" in lower else None)
        )
        if not marker:
            continue
        idx = lower.find(marker)
        name_part = line[idx:]
        name_part = re.split(r"\s+[—–-]\s+", name_part)[0].strip()
        baseline_match = re.search(
            r"baseline\s*,?\s*(20\d{2})?\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)",
            line,
            re.IGNORECASE,
        )
        quota_match = re.search(r"quota\s*:?\s*(\d+)", line, re.IGNORECASE)
        year_match = re.search(r"(20\d{2})", line)
        field_slug = re.sub(r"[^a-z0-9]+", "-", name_part.lower()).strip("-")
        departments.append(
            {
                "name": name_part,
                "field_key": field_slug,
                "degree": "bachelor",
                "duration_years": 4,
                "language": "",
                "application_deadline": deadline,
                "admissions": (
                    [
                        {
                            "year": int(
                                baseline_match.group(1)
                                or (year_match.group(1) if year_match else 2025)
                            ),
                            "baseline_score": float(baseline_match.group(2)),
                            "top_score": None,
                            "quota": int(quota_match.group(1)) if quota_match else None,
                            "units": "points",
                            "confidence": 0.9,
                        }
                    ]
                    if baseline_match
                    else []
                ),
            }
        )
    return {
        "universities": [
            {
                "name": uni_name,
                "country": "",
                "city": "",
                "university_type": "public",
                "departments": departments,
            }
        ]
    }


register_mock_fixture(AITaskType.UNIVERSITY_PARSE, _mock_extraction)


async def parse_universities(
    db: AsyncSession, user_id, text: str
) -> UniversityExtraction:
    """Extract structured universities/departments/admissions from raw text."""
    return await ainvoke_structured(
        db,
        AITaskType.UNIVERSITY_PARSE,
        UniversityExtraction,
        system="Extract universities, departments and admission baselines precisely.",
        user=_build_user_prompt(text),
        user_id=user_id,
    )
