"""Deterministic posting safety signals (plan 212 S3.2).

Six factual checks with a verbatim evidence quote each. This is not a
scam score or verdict: a flag says "check this", and no flag means "we
found nothing in the text we inspect", never "this is safe".
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_model import Job
from app.models.posting_model import JobPosting
from app.schemas.posting import PostingSafetyFlagOut
from app.services.postings.text import plain_text

PERSONAL_DOMAINS = (
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "live.com",
    "protonmail.com",
    "icloud.com",
    "gmx.de",
    "gmx.net",
    "gmx.at",
    "gmx.ch",
    "web.de",
    "t-online.de",
    "mail.ru",
    "yandex.com",
)
SHORTENER_HOSTS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd"}
MESSAGING = re.compile(
    r"\b(whatsapp|telegram|signal|viber)\b[^.\n]{0,60}\b"
    r"(contact|message|chat|apply|interview|phone|number)\b"
    r"|\b(contact|message|chat|apply|interview|phone|number)\b[^.\n]{0,60}"
    r"\b(whatsapp|telegram|signal|viber)\b",
    re.IGNORECASE,
)
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})\b", re.IGNORECASE)
FEE_PATTERNS = (
    re.compile(
        r"\b(application|processing|registration|training|admin(?:istration)?)\s+fee\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:pay|send|requires?)\b[^.\n]{0,60}\b(?:fee|deposit|to apply)\b", re.IGNORECASE
    ),
    re.compile(r"\bfee\b[^.\n]{0,24}\b(?:required|to apply)\b", re.IGNORECASE),
)
VAGUE_ORGS = {
    "",
    "confidential",
    "private",
    "private company",
    "a leading company",
    "leading company",
    "our client",
    "company",
    "client",
}


def _text(posting: JobPosting) -> str:
    raw = posting.raw or {}
    parts = [plain_text(str(raw.get("description") or ""))]
    extract = posting.extract or {}
    if isinstance(extract, dict):
        parts.append(plain_text(str(extract.get("description_clean") or "")))
    return "\n".join(part for part in parts if part)


def _evidence(text: str, pattern: re.Pattern) -> str:
    for line in text.splitlines():
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            if pattern.search(sentence):
                return " ".join(sentence.split())[:300]
    return ""


def _salary_band(job: Job | None) -> tuple[float, float, str] | None:
    if job is None:
        return None
    attributes = job.attributes or {}
    salary = attributes.get("salary")
    if not isinstance(salary, dict):
        return None
    median = salary.get("median")
    if not isinstance(median, (list, tuple)) or len(median) != 2:
        return None
    try:
        low, high = float(median[0]), float(median[1])
    except (TypeError, ValueError):
        return None
    return (min(low, high), max(low, high), str(salary.get("currency") or "").upper())


async def posting_safety_flags(
    db: AsyncSession, posting: JobPosting, job: Job | None = None
) -> list[PostingSafetyFlagOut]:
    text = _text(posting)
    flags: list[PostingSafetyFlagOut] = []

    for pattern in FEE_PATTERNS:
        quote = _evidence(text, pattern)
        if quote and not _fee_negated(quote):
            flags.append(
                PostingSafetyFlagOut(
                    key="fee_requested",
                    label="Payment or fee mentioned",
                    evidence=quote,
                )
            )
            break

    personal_email = next(
        (
            match
            for match in EMAIL.finditer(text)
            if match.group(1).lower().removeprefix("www.") in PERSONAL_DOMAINS
        ),
        None,
    )
    if personal_email is not None:
        flags.append(
            PostingSafetyFlagOut(
                key="personal_email_domain",
                label="Personal email domain",
                evidence=personal_email.group(0)[:300],
            )
        )

    messaging = MESSAGING.search(text)
    if messaging is not None:
        quote = _evidence(text, MESSAGING)
        flags.append(
            PostingSafetyFlagOut(
                key="messaging_app_contact",
                label="Messaging-app contact",
                evidence=quote or messaging.group(0),
            )
        )

    org = " ".join((posting.org or "").lower().split())
    if org in VAGUE_ORGS or "confidential" in org:
        flags.append(
            PostingSafetyFlagOut(
                key="vague_org",
                label="Organisation is vague",
                evidence=(posting.org or "").strip()[:300] or "No organisation name",
            )
        )

    band = _salary_band(job)
    posted_low = posting.salary_normalized_min or posting.salary_min
    posting_currency = (posting.salary_currency or "").upper()
    if (
        band is not None
        and posted_low is not None
        and band[1] > 0
        and posting_currency
        and band[2]
        and posting_currency == band[2]
        and posted_low > band[1] * 3
    ):
        flags.append(
            PostingSafetyFlagOut(
                key="salary_outlier",
                label="Pay far above the catalog band",
                evidence=(
                    f"Posted range starts at {posted_low:,.0f} {posting_currency}; "
                    f"catalog median upper band is {band[1]:,.0f} {band[2]}."
                ),
            )
        )

    host = (urlparse(posting.url or "").hostname or "").lower().removeprefix("www.")
    personal_host = any(host == d or host.endswith(f".{d}") for d in PERSONAL_DOMAINS)
    if host in SHORTENER_HOSTS or personal_host:
        flags.append(
            PostingSafetyFlagOut(
                key="url_mismatch",
                label="Shortened or personal link",
                evidence=(posting.url or "")[:300],
            )
        )

    return flags


def _fee_negated(sentence: str) -> bool:
    lowered = f" {sentence.lower()} "
    return any(
        phrase in lowered
        for phrase in (
            "no fee",
            "no application fee",
            "not charge",
            "fee is covered",
            "fees are covered",
            "covers the fee",
            "covers the processing fee",
            "employer pays",
            "we pay",
            "fee-free",
            "free to apply",
        )
    )
