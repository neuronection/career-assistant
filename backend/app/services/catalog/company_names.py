"""Company-name canonicalization: the pure, dialect-free functions the
organization matcher is built on.

Split of duties: structural quality rules live here in code (a label with
no letters is never a company — linguistic knowledge, not per-install
policy); the generic *label* denylist ("confidential", "staffing", …)
seeds as global `organization_match_exclusions` rows (migration 0070) so
the rules surface edits it without a deploy.
"""

import re
from urllib.parse import urlparse

TOKEN = re.compile(r"[a-z0-9]+")

# Corporate/legal suffixes dropped before comparison — "Acme Cloud GmbH"
# and "Acme Cloud" are the same employer everywhere.
LEGAL_SUFFIXES = frozenset(
    {
        "gmbh",
        "mbh",
        "ag",
        "kg",
        "ohg",
        "ltd",
        "limited",
        "llc",
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "sa",
        "sas",
        "srl",
        "spa",
        "bv",
        "nv",
        "plc",
        "oy",
        "ab",
        "as",
        "pty",
    }
)

_SLUG_CLEAN = re.compile(r"[^a-z0-9-]+")

# ATS boards where the first path segment (or the subdomain) is the
# employer slug — the strongest non-name linking signal.
_BOARD_PATH_SLUGS = frozenset(
    {
        "boards.greenhouse.io",
        "jobs.lever.co",
        "jobs.ashbyhq.com",
        "jobs.workday.com",
    }
)
_BOARD_SUBDOMAIN_SLUGS = frozenset({"teamtailor.com", "smartrecruiters.com"})
_EMPLOYER_PREFIXES = ("careers.", "jobs.", "apply.")


def tokens(name: str) -> list[str]:
    return [t for t in TOKEN.findall(name.lower()) if t not in LEGAL_SUFFIXES]


def canonical(name: str) -> str:
    """Legal-suffix-stripped comparison form (the legacy `_canonical`)."""
    return " ".join(tokens(name))


def name_key(name: str) -> str:
    """Indexed exact-lookup key: the canonical form."""
    return canonical(name)[:200]


def initials_key(name: str) -> str:
    """Indexed initialism key: "P&G" → "pg", "Procter & Gamble" → "pg".

    Meaningful only for multi-token names and short codes — a single long
    token ("DupOne") has no initialism, and its first letter would collide
    with every employer starting on the same letter.
    """
    name_tokens = tokens(name)
    if len(name_tokens) >= 2:
        return "".join(t[0] for t in name_tokens)[:200]
    if name_tokens and len(name_tokens[0]) <= 4:
        return name_tokens[0]
    return ""


def alias_key(alias: str) -> str:
    """The comparison form of an alias row (same canonicalization)."""
    return name_key(alias)


def quality_ok(label: str | None) -> str | None:
    """Structural gate for raw employer labels; None passes, else the reason.

    Word-based junk ("confidential", "staffing agency") is data, not code:
    it lives in seeded global exclusion rows the admin can edit.
    """
    label = (label or "").strip()
    if not label:
        return "empty"
    if len(label) < 2:
        return "too_short"
    if len(label) > 200:
        return "too_long"
    letters = sum(ch.isalpha() for ch in label)
    if letters < 2 or letters / len(label) < 0.3:
        return "low_letters"
    if label.endswith(("…", "...", "-")):
        return "truncated"
    return None


def url_company_signal(url: str | None) -> dict | None:
    """The employer signal in a posting URL: {"domain", "slug"} or None.

    Supports the ATS board shapes (greenhouse/lever/ashby/workday first
    path segment, teamtailor/smartrecruiters subdomains) and the
    careers./jobs./apply. host prefixes.
    """
    raw = (url or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = f"https://{raw}"
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if not host or "." not in host:
        return None
    if _is_ip_host(host):
        return None
    segments = [seg for seg in parsed.path.split("/") if seg]
    slug: str | None = None
    if host in _BOARD_PATH_SLUGS and segments:
        slug = _clean_slug(segments[0])
    else:
        for base in _BOARD_SUBDOMAIN_SLUGS:
            if host.endswith(f".{base}"):
                slug = _clean_slug(host[: -len(base) - 1].split(".")[-1])
                break
        if slug is None:
            for prefix in _EMPLOYER_PREFIXES:
                if host.startswith(prefix):
                    slug = _clean_slug(host[len(prefix) :].split(".")[0])
                    break
    if slug is None:
        return None
    if not slug:
        return None
    return {"domain": host, "slug": slug}


def _is_ip_host(host: str) -> bool:
    parts = host.split(".")
    return len(parts) == 4 and all(p.isdigit() for p in parts)


def _clean_slug(value: str) -> str:
    return _SLUG_CLEAN.sub("", value.lower())[:60]
