"""The parser view (plan 212 S1.2): what OUR extractor sees.

Prints the CV's current state through the same engine as the PDF export
(no version created), then extracts each printed page's text with
pypdfium2 — the same library that counts pages. Deterministic findings
only: a missing text layer, contact details that did not survive
extraction, welded (joined) lines, a section order that deviates from
the rendered reading order, page overflow vs the budget and empty
pages. No score, no vendor names: this is what this app's own
extractor sees, never a claim about any ATS product.
"""

import re

import pypdfium2 as pdfium

from app.schemas.cv_export import CvParseViewFinding, CvParseViewOut, CvParseViewPage
from app.services.cv.cv_builder_service import CvBuilderService
from app.services.cv.cv_export_service import _heading_of, _visible_blocks
from app.services.cv.cv_pdf_service import html_to_pdf

# A printed CV line longer than this reads as two spans joined without
# the whitespace a parser needs (the "welded lines" suspicion).
WELDED_LINE_CHARS = 200
# Wire bounds: `page_count` is never clamped; the per-page text list is.
MAX_TEXT_PAGES = 20
MAX_PAGE_CHARS = 20_000
MIN_PHONE_DIGITS = 7


def extract_page_texts(pdf: bytes) -> tuple[int, list[str]]:
    """Per-page text via pdfium — the page count is the PDF's own tree,
    the text bounded to `MAX_TEXT_PAGES` pages on the wire."""
    document = pdfium.PdfDocument(pdf)
    try:
        count = len(document)
        texts: list[str] = []
        for index in range(min(count, MAX_TEXT_PAGES)):
            page = document[index]
            textpage = page.get_textpage()
            try:
                texts.append(textpage.get_text_range()[:MAX_PAGE_CHARS])
            finally:
                textpage.close()
                page.close()
        return count, texts
    finally:
        document.close()


def _line_count(text: str) -> int:
    return len([line for line in text.splitlines() if line.strip()])


def _rendered_headings(payload: dict, template: object | None) -> list[str]:
    """Section headings in rendered reading order (lint parity: the
    sidebar column first when `side=left`)."""
    from app.services.cv.cv_export_service import _render_order

    snapshot = payload.get("snapshot") or {}
    return [
        _heading_of(kind, props).strip().lower()
        for kind, props, _data in _visible_blocks(
            _render_order(payload.get("blocks") or [], template), snapshot
        )
        if kind not in ("header", "letter")
    ]


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _findings(
    payload: dict,
    template: object | None,
    texts: list[str],
    page_count: int,
    max_pages: int,
) -> list[CvParseViewFinding]:
    """Deterministic findings, in a fixed order. Clean CVs emit none —
    the OK facts live on `text_layer`/`page_count`, not in the list."""
    findings: list[CvParseViewFinding] = []
    haystack = "\n".join(texts).lower()
    text_layer = bool(haystack.strip())

    if not text_layer:
        findings.append(
            CvParseViewFinding(
                id="text_layer",
                level="fail",
                message=(
                    "No text layer in the printed PDF — a parser reads "
                    "nothing from these pages (image-only export)."
                ),
            )
        )
        return findings

    basics = (payload.get("snapshot") or {}).get("basics") or {}
    missing_contact = []
    email = str(basics.get("email") or "").strip().lower()
    if email and email not in haystack:
        missing_contact.append("email")
    phone = _digits(str(basics.get("phone") or ""))
    if len(phone) >= MIN_PHONE_DIGITS and phone not in _digits(haystack):
        missing_contact.append("phone")
    if missing_contact:
        findings.append(
            CvParseViewFinding(
                id="header_contact",
                level="warn",
                message=(
                    "Your "
                    + " and ".join(missing_contact)
                    + " did not survive extraction — it may sit in a "
                    "header/footer line that parsers drop."
                ),
            )
        )

    welded = [
        line.strip()
        for text in texts
        for line in text.splitlines()
        if len(line.strip()) > WELDED_LINE_CHARS
    ]
    if welded:
        findings.append(
            CvParseViewFinding(
                id="welded_lines",
                level="warn",
                message=(
                    f"{len(welded)} line(s) over {WELDED_LINE_CHARS} characters — "
                    "long spans read as welded together; add the missing "
                    "line breaks."
                ),
            )
        )

    headings = [heading for heading in _rendered_headings(payload, template) if heading]
    positions = [haystack.find(heading) for heading in headings]
    found = [position for position in positions if position >= 0]
    if len(found) >= 2 and found != sorted(found):
        findings.append(
            CvParseViewFinding(
                id="reading_order",
                level="warn",
                message=(
                    "Sections appear in a different order in the extracted "
                    "text than in the document — column layouts can be read "
                    "in the wrong sequence."
                ),
            )
        )

    if page_count > max_pages:
        findings.append(
            CvParseViewFinding(
                id="page_overflow",
                level="warn",
                message=(
                    f"Measured {page_count} pages exceed the {max_pages}-page "
                    "budget — densify or trim; the budget never grows."
                ),
            )
        )

    empty = [index + 1 for index, text in enumerate(texts) if not text.strip()]
    if empty:
        findings.append(
            CvParseViewFinding(
                id="empty_page",
                level="warn",
                message=(
                    f"Page(s) {', '.join(str(n) for n in empty)} extract no "
                    "text — a trailing blank page or an image-only page."
                ),
            )
        )
    return findings


class CvParseViewService:
    """Builds the parse view for one CV's current state."""

    def __init__(self, db):
        self.builder = CvBuilderService(db)

    async def build(self, cv) -> CvParseViewOut:
        """Render (no version), print, extract, analyze — everything
        deterministic; no AI and no vendor claims anywhere."""
        html, payload, _resolution, _metrics = await self.builder.render_state(cv)
        pdf = await html_to_pdf(html)
        page_count, texts = extract_page_texts(pdf)
        template = await self.builder.template_row(cv)
        return CvParseViewOut(
            pages=[
                CvParseViewPage(index=index, text=text, line_count=_line_count(text))
                for index, text in enumerate(texts)
            ],
            findings=_findings(payload, template, texts, page_count, cv.max_pages),
            page_count=page_count,
            text_layer=bool("\n".join(texts).strip()),
            engine="pdf",
        )
