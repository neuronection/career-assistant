"""CV parser agent: CV text → structured `CvExtract` draft.

One audited structured call (`CV_PARSE`). The mock fixture parses simple
marker lines deterministically so the whole intake flow runs offline in
tests; real (non-marker) text falls through to plain-text heuristics so
dev behaves like a real provider. Nothing here writes to the profile —
the draft lands in `cv_parse_drafts` and the user confirms every item
(review-first).
"""

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.context import context_json, parse_context
from app.ai.gateway import ainvoke_structured, register_mock_fixture
from app.ai.schemas import UniversityExtraction  # noqa: F401 - pattern parity
from app.models.enums import AITaskType
from app.schemas.cv_extract import CvExtract
from app.services.cv_field_map import build_extraction_prompt

_DATE = r"(\d{4}-\d{2}|\d{4})"


def _mock_cv_extract(schema: type, user_prompt: str) -> dict:
    """Deterministic offline extraction from marker-formatted text.

    Recognized markers (one per line):
      NAME: … | HEADLINE: … | EMAIL: … | PHONE: … | LOCATION: …
      LINK: kind=url
      SUMMARY: …
      EDUCATION: program at institution (start - end)
      EXPERIENCE: title at org (start - end); description
      SKILL: name [: level]
      LANGUAGE: code level
      CERTIFICATION: name — issuer
      AWARD: kind | title — issuer (date)
      INTEREST: label
    """
    ctx = parse_context(user_prompt)
    text = str(ctx.get("cv_text", ""))
    out: dict = {
        "basics": {},
        "education": [],
        "experience": [],
        "skills": [],
        "languages": [],
        "certifications": [],
        "awards": [],
        "interests": [],
    }
    simple = {
        "NAME": ("full_name", "basics"),
        "HEADLINE": ("headline", "basics"),
        "EMAIL": ("email", "basics"),
        "PHONE": ("phone", "basics"),
        "LOCATION": ("location", "basics"),
        "SUMMARY": (None, "summary"),
    }
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for marker, (field, target) in simple.items():
            if line.upper().startswith(f"{marker}:"):
                value = line.split(":", 1)[1].strip()
                if target == "summary":
                    out["summary"] = value
                elif field:
                    out["basics"][field] = value
                break
        else:
            upper = line.upper()
            if upper.startswith("LINK:"):
                _, rest = line.split(":", 1)
                kind, url = rest.split("=", 1)
                out["basics"].setdefault("links", []).append(
                    {"kind": kind.strip(), "url": url.strip()}
                )
            elif upper.startswith("EDUCATION:"):
                body = line.split(":", 1)[1]
                period = re.search(rf"\({_DATE}\s*-\s*({_DATE}|present)\)", body, re.I)
                body_clean = re.sub(
                    rf"\({_DATE}\s*-\s*({_DATE}|present)\)", "", body, flags=re.I
                )
                if " at " in body_clean:
                    program, institution = body_clean.split(" at ", 1)
                else:
                    program, institution = body_clean, body_clean
                out["education"].append(
                    {
                        "institution": institution.strip(),
                        "program": program.strip(),
                        "start": period.group(1) if period else "",
                        "end": period.group(2) if period else "",
                        "evidence": {"quote": line[:200], "confidence": 0.9},
                    }
                )
            elif upper.startswith("EXPERIENCE:"):
                body = line.split(":", 1)[1]
                period = re.search(rf"\({_DATE}\s*-\s*({_DATE}|present)\)", body, re.I)
                body_clean = re.sub(
                    rf"\({_DATE}\s*-\s*({_DATE}|present)\)", "", body, flags=re.I
                )
                title_at, _, description = body_clean.partition(";")
                title, _, org = title_at.partition(" at ")
                out["experience"].append(
                    {
                        "kind": "job",
                        "title": title.strip(),
                        "org": org.strip(),
                        "start": period.group(1) if period else "",
                        "end": period.group(2) if period else "",
                        "description": description.strip(),
                        "skills": [],
                        "achievements": [],
                        "evidence": {"quote": line[:200], "confidence": 0.9},
                    }
                )
            elif upper.startswith("SKILL:"):
                body = line.split(":", 1)[1].strip()
                name, _, level = body.partition(":")
                skill: dict = {
                    "name": name.strip(),
                    "evidence": {"quote": line[:200], "confidence": 0.85},
                }
                if level.strip().isdigit():
                    skill["level_claim"] = min(10, max(1, int(level.strip())))
                out["skills"].append(skill)
            elif upper.startswith("LANGUAGE:"):
                body = line.split(":", 1)[1].strip()
                code, _, level = body.partition(" ")
                level = level.strip() or "intermediate"
                if level not in ("basic", "intermediate", "advanced", "native"):
                    level = "intermediate"
                out["languages"].append(
                    {
                        "code": code.strip(),
                        "level": level,
                        "evidence": {"quote": line[:200], "confidence": 0.9},
                    }
                )
            elif upper.startswith("CERTIFICATION:"):
                body = line.split(":", 1)[1]
                name, _, issuer = body.partition(" — ")
                out["certifications"].append(
                    {
                        "name": name.strip(),
                        "issuer": issuer.strip(),
                        "evidence": {"quote": line[:200], "confidence": 0.9},
                    }
                )
            elif upper.startswith("AWARD:"):
                body = line.split(":", 1)[1]
                kind, _, rest = body.partition("|")
                kind = kind.strip()
                if kind not in ("award", "honor", "publication", "extracurricular"):
                    kind = "award"
                title, _, issuer_date = rest.partition(" — ")
                issuer, _, date = issuer_date.partition("(")
                out["awards"].append(
                    {
                        "kind": kind,
                        "title": title.strip(),
                        "issuer": issuer.strip(),
                        "date": date.strip(") "),
                        "evidence": {"quote": line[:200], "confidence": 0.9},
                    }
                )
            elif upper.startswith("INTEREST:"):
                out["interests"].append(
                    {
                        "label": line.split(":", 1)[1].strip(),
                        "evidence": {"quote": line[:200], "confidence": 0.8},
                    }
                )
    if _marker_pass_empty(out):
        out = _heuristic_plain_text_extract(text) or out
    return out


def _marker_pass_empty(out: dict) -> bool:
    """True when the marker pass found nothing usable (real CV text)."""
    return not (
        out["basics"]
        or out["education"]
        or out["experience"]
        or out["skills"]
        or out["languages"]
        or out["certifications"]
        or out["awards"]
        or out["interests"]
    )


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_SEPARATOR = re.compile(r"\s+[—–|]\s+|\s+ at \s+|\s+-\s+")


def _heuristic_line(line: str) -> dict:
    """Extract the structured guess for one plain-text CV line."""
    return {"quote": line[:200], "page": 0, "confidence": 0.55}


def _heuristic_plain_text_extract(text: str) -> dict | None:
    """Best-effort extraction from real (non-marker) CV text — dev only.

    The mock provider must feel like a real LLM offline, so plain OCR
    text gets deterministic regex heuristics: contact fields, sectioned
    Skills, `Title — Org`-style experience/education lines and a summary
    paragraph. Confidence stays at 0.55 (a guess, review-first applies
    regardless).
    """
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return None
    out: dict = {
        "basics": {},
        "summary": "",
        "education": [],
        "experience": [],
        "skills": [],
        "languages": [],
        "certifications": [],
        "awards": [],
        "interests": [],
    }
    for line in lines:
        email = _EMAIL.search(line)
        if email and "email" not in out["basics"]:
            out["basics"]["email"] = email.group(0)
        phone = _PHONE.search(line)
        if phone and "phone" not in out["basics"] and not _EMAIL.search(phone.group(0)):
            out["basics"]["phone"] = phone.group(0).strip()
    for line in lines:
        words = line.split()
        if (
            "full_name" not in out["basics"]
            and 1 <= len(words) <= 4
            and not any(ch.isdigit() for ch in line)
            and "@" not in line
            and not _PHONE.search(line)
        ):
            out["basics"]["full_name"] = line
            out["basics"]["evidence"] = _heuristic_line(line)
            break
    section: str | None = None
    for line in lines:
        lower = line.lower().strip(":• ")
        if re.fullmatch(r"(skills?)(\s*(&|/)\s*(tools?|technologies?))?", lower):
            section = "skills"
            continue
        if re.fullmatch(r"(experience|employment|work history)", lower):
            section = "experience"
            continue
        if re.fullmatch(r"(education|studies)", lower):
            section = "education"
            continue
        if re.fullmatch(r"(summary|profile|about)( me)?", lower):
            section = "summary"
            continue
        if lower in ("languages", "certifications", "interests", "projects"):
            section = None
            continue
        if section == "skills" and len(out["skills"]) < 10:
            for part in re.split(r"[,;·/]", line):
                name = part.strip(" .-•")
                if 1 <= len(name) <= 40 and not _EMAIL.search(name):
                    out["skills"].append(
                        {"name": name, "evidence": _heuristic_line(line)}
                    )
        elif section == "experience" and len(out["experience"]) < 8:
            parts = _SEPARATOR.split(line, maxsplit=1)
            if len(parts) == 2:
                title, org = parts[0].strip(), parts[1].strip()
                period = re.search(rf"(?:{_DATE})\s*-\s*({_DATE}|present)", line, re.I)
                org = re.sub(
                    rf"\s*\((?:{_DATE})\s*-\s*(?:{_DATE}|present)\)\s*$",
                    "",
                    org,
                    flags=re.I,
                )
                out["experience"].append(
                    {
                        "kind": "job",
                        "title": title,
                        "org": org,
                        "start": period.group(1) if period else "",
                        "end": period.group(2) if period else "",
                        "description": "",
                        "skills": [],
                        "achievements": [],
                        "evidence": _heuristic_line(line),
                    }
                )
        elif section == "education" and len(out["education"]) < 5:
            parts = _SEPARATOR.split(line, maxsplit=1)
            if len(parts) == 2:
                program, institution = parts[0].strip(), parts[1].strip()
                period = re.search(rf"(?:{_DATE})\s*-\s*({_DATE}|present)", line, re.I)
                institution = re.sub(
                    rf"\s*\((?:{_DATE})\s*-\s*(?:{_DATE}|present)\)\s*$",
                    "",
                    institution,
                    flags=re.I,
                )
                out["education"].append(
                    {
                        "institution": institution,
                        "program": program,
                        "start": period.group(1) if period else "",
                        "end": period.group(2) if period else "",
                        "evidence": _heuristic_line(line),
                    }
                )
        elif section == "summary" and len(out["summary"]) < 800:
            out["summary"] = f"{out['summary']} {line}".strip()
    if not (
        out["basics"]
        or out["education"]
        or out["experience"]
        or out["skills"]
        or out["summary"]
    ):
        return None
    return out


register_mock_fixture(AITaskType.CV_PARSE, _mock_cv_extract)


async def parse_cv(db: AsyncSession, user_id, cv_text: str) -> CvExtract:
    """One structured AI pass over the CV text (audited; draft only)."""
    return await ainvoke_structured(
        db,
        AITaskType.CV_PARSE,
        CvExtract,
        system=build_extraction_prompt(),
        user=context_json({"cv_text": cv_text[:20000]}),
        user_id=user_id,
    )
