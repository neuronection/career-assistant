"""Language-display support for CV blocks: human names, CEFR mapping and
language-proficiency certification enrichment.

All three are curated data (`code → name`, `level → CEFR`, exam-keyword →
language) resolved deterministically; templates pick presentation via
block props, never via rendering logic.
"""

import re

LANGUAGE_NAMES: dict[str, str] = {
    "el": "Greek",
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "sv": "Swedish",
    "pl": "Polish",
    "tr": "Turkish",
    "ru": "Russian",
    "ar": "Arabic",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "hi": "Hindi",
    "ur": "Urdu",
    "fa": "Persian",
    "ro": "Romanian",
    "hu": "Hungarian",
    "cs": "Czech",
    "sk": "Slovak",
    "uk": "Ukrainian",
    "he": "Hebrew",
    "bn": "Bengali",
    "id": "Indonesian",
    "ms": "Malay",
    "th": "Thai",
    "vi": "Vietnamese",
}

# Level vocabulary (profile UI: basic | intermediate | advanced | native)
# → representative CEFR band.
LEVEL_CEFR: dict[str, str] = {
    "basic": "A1–A2",
    "intermediate": "B1–B2",
    "advanced": "C1",
    "native": "Native",
}

# Language-proficiency exam vocabulary: keyword (matched against
# title/issuer, case-insensitive) → implied language code. "proficienc"
# catches generic names ("English Proficiency Certificate") whose target
# language is resolved separately via the language name in the text.
PROFICIENCY_EXAMS: dict[str, str] = {
    "toefl": "en",
    "ielts": "en",
    "cambridge": "en",
    "ef set": "en",
    "duolingo english": "en",
    "trinity": "en",
    "goethe": "de",
    "telc": "de",
    "delf": "fr",
    "dalf": "fr",
    "tcf": "fr",
    "dele": "es",
    "cie": "es",
    "celi": "it",
    "cils": "it",
    "tömer": "tr",
    "torfl": "ru",
    "jlpt": "ja",
    "topik": "ko",
    "hsk": "zh",
}


def language_name(code: str) -> str:
    """Human language name for a code the name map knows.

    On-demand vocabularies (profile combobox, intake LLM) may store a
    full English name as the "code" ("hindi") when no ISO code matched:
    those render as a title-cased phrase, shorter unknown snippets fall
    back to the upper-case code.
    """
    cleaned = (code or "").strip()
    named = LANGUAGE_NAMES.get(cleaned.lower())
    if named:
        return named
    if " " in cleaned or len(cleaned) > 5:
        return " ".join(word.capitalize() for word in cleaned.split())
    return cleaned.upper()


def cefr_of(level: str) -> str:
    """Representative CEFR band for a profile level ("" when unknown)."""
    return LEVEL_CEFR.get(str(level).strip().lower(), "")


def _implied_language(haystack: str) -> str:
    lowered = haystack.lower()
    for keyword, code in PROFICIENCY_EXAMS.items():
        # Word-boundary matching keeps short exam codes ("CIE") from
        # matching inside ordinary words ("proficiency").
        if re.search(rf"(?<![a-z]){re.escape(keyword.lower())}(?![a-z])", lowered):
            return code
    return ""


def is_proficiency_cert(cert: dict) -> bool:
    """A certification that acts as language-proficiency proof."""
    if cert.get("language_code"):
        return True  # an explicit link always counts as proof
    text = f"{cert.get('title') or ''} {cert.get('org') or ''}".strip()
    if not text:
        return False
    lowered = text.lower()
    if "proficienc" in lowered or "cefr" in lowered:
        return True
    return bool(_implied_language(lowered))


def match_language(cert: dict, languages: list[dict]) -> str:
    """The language a proficiency certificate proves ("" when none).

    Priority: an explicit `language_code` on the certification, then an
    exam name's implied language, then the language name or code in the
    certificate text.
    """
    explicit = str(cert.get("language_code") or "").strip().lower()
    if explicit:
        return explicit
    text = f"{cert.get('title') or ''} {cert.get('org') or ''}".strip()
    if not text:
        return ""
    implied = _implied_language(text.lower())
    if implied:
        return implied
    lowered = text.lower()
    for language in languages:
        code = str(language.get("code") or "").lower()
        name = language_name(code).lower()
        if (code and code in lowered) or (name and name in lowered):
            return code
    return ""


def proficiency_for(
    languages: list[dict], certifications: list[dict]
) -> dict[str, dict]:
    """Latest proficiency certificate per language code.

    Certifications arrive resolver-ordered (newest issued first). An
    explicit `language_code` on the certification claims its language
    first; after those, derived exam matching claims the first match
    per language. Every claimed certificate stays claimable for display
    and dedupe decisions.
    """
    claimed: dict[str, dict] = {}
    if not languages:
        return claimed
    for cert in certifications:
        code = str(cert.get("language_code") or "").strip().lower()
        if code:
            claimed.setdefault(code, cert)
    for cert in certifications:
        if not is_proficiency_cert(cert):
            continue
        code = match_language(cert, languages)
        if code and code not in claimed:
            claimed[code] = cert
    return claimed
