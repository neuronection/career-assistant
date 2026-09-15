"""CV exports + deterministic ATS lint.

Every export compiles the current state first (auto-version,
`created_by=export`), then serializes the compiled snapshot — an exported
file is always exactly an immutable version. PDF is the renderer's
print-ready HTML printed through headless Chromium (capability-detected;
without it the client falls back to the print view).
"""

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from app.core.errors import ValidationError
from app.models.cv_model import CvDocument, CvVersion
from app.models.enums import CvSynthStatus, CvVersionCreator
from app.services.cv_builder_service import CvBuilderService
from app.services.cv_languages import is_proficiency_cert, proficiency_for
from app.services.cv_pdf_service import (
    PDFEngineUnavailable,
    count_pdf_pages,
    html_to_pdf,
    measure_pages,
)
from app.services.cv_renderer import (
    default_section_title,
    _display_link,
    custom_text_blocks,
)
from app.services.cv_blocks import block_area

ExportFormat = Literal["pdf", "docx", "md", "json", "ats_text"]

STANDARD_HEADINGS = {
    "summary",
    "experience",
    "work experience",
    "education",
    "certifications",
    "projects",
    "volunteering",
    "volunteer",
    "skills",
    "languages",
    "achievements",
    "interests",
}

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "md": "text/markdown",
    "json": "application/json",
    "ats_text": "text/plain",
}

EXTENSIONS = {
    "pdf": "pdf",
    "docx": "docx",
    "md": "md",
    "json": "json",
    "ats_text": "txt",
}


@dataclass
class ExportFile:
    """One serialized export ready for an HTTP response."""

    filename: str
    media_type: str
    content: bytes
    inline: bool


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug or "cv"


def _period(item: dict) -> str:
    start, end = str(item.get("start") or ""), str(item.get("end") or "")
    return " – ".join(part for part in (start, end) if part)


def _heading_of(kind: str, props: dict) -> str:
    if kind == "summary":
        return props.get("title") or "Summary"
    if kind == "items":
        return props.get("title") or default_section_title(
            props.get("source_key") or "", "en"
        )
    return props.get("title") or kind.replace("_", " ").title()


def _visible_blocks(blocks: list[dict], snapshot: dict) -> list[tuple[str, dict, dict]]:
    """Blocks that carry content, in render order (renderer parity)."""
    visible: list[tuple[str, dict, dict]] = []
    for block in blocks:
        kind, props = str(block.get("kind")), dict(block.get("props") or {})
        if kind == "spacer":
            continue
        if kind == "header":
            if (snapshot.get("basics") or {}).get("name"):
                visible.append((kind, props, snapshot.get("basics") or {}))
            continue
        if kind == "custom_text":
            if not str(props.get("text") or "").strip():
                continue
            visible.append((kind, props, {"text": props.get("text") or ""}))
            continue
        if kind == "letter":
            paragraphs = [
                str(p) for p in props.get("paragraphs") or [] if str(p).strip()
            ]
            if not paragraphs:
                continue
            visible.append((kind, props, {"paragraphs": paragraphs}))
            continue
        if kind == "summary":
            if snapshot.get("summary"):
                visible.append((kind, props, {"summary": snapshot["summary"]}))
            continue
        if kind == "synth_items":
            entries = snapshot.get("synth") or []
            selected = [str(x) for x in props.get("selected") or []]
            if selected:
                chosen = set(selected)
                entries = [
                    entry
                    for entry in entries
                    if isinstance(entry, dict) and str(entry.get("id")) in chosen
                ]
            entries = entries[: int(props.get("max_items") or 20)]
            if entries:
                visible.append((kind, props, entries))
            continue
        data = snapshot.get(str(props.get("source_key") or kind))
        if data:
            if kind == "items" and props.get("exclude_proficiency"):
                data = [i for i in data if not is_proficiency_cert(i)]
                if not data:
                    continue
            visible.append((kind, props, data))
    return visible


def _language_line(lang: dict, props: dict, snapshot: dict) -> str:
    """One language entry text, honoring CEFR + proficiency enrichment."""
    label = str(lang.get("label") or lang.get("code") or "")
    level = str(lang.get("level") or "")
    line = f"{label} — {level}" if level else label
    if props.get("show_cefr") and lang.get("cefr"):
        line = f"{line} ({lang.get('cefr')})"
    if props.get("show_proficiency"):
        cert = proficiency_for([lang], snapshot.get("certifications") or []).get(
            lang.get("code") or ""
        )
        if cert:
            line = f"{line} · {cert.get('title') or ''}" + (
                f", {cert.get('start')}" if cert.get("start") else ""
            )
    return line


def _item_head(item: dict) -> str:
    return " — ".join(
        part
        for part in (
            str(item.get("title") or item.get("program") or ""),
            str(item.get("org") or item.get("institution") or ""),
        )
        if part
    )


def to_markdown(version_payload: dict) -> str:
    """Deterministic markdown of a compiled version (renderer order)."""
    snapshot = version_payload.get("snapshot") or {}
    blocks = version_payload.get("blocks") or []
    lines: list[str] = []
    for kind, props, data in _visible_blocks(blocks, snapshot):
        if kind == "header":
            lines.append(f"# {data.get('name') or ''}")
            contact = " · ".join(
                str(data.get(field) or "")
                for field in ("headline", "email", "phone", "location")
                if data.get(field)
            )
            if contact:
                lines.append(contact)
            links = " · ".join(
                f"[{link.get('label') or link.get('kind') or 'link'}]"
                f"({link.get('url')})"
                for link in data.get("links") or []
            )
            if links:
                lines.append(links)
        elif kind == "summary":
            lines.append(f"## {_heading_of(kind, props)}")
            lines.append(str(data.get("summary") or ""))
        elif kind == "items":
            lines.append(f"## {_heading_of(kind, props)}")
            for item in data:
                period = _period(item)
                lines.append(
                    f"### {_item_head(item)}" + (f" ({period})" if period else "")
                )
                if item.get("description"):
                    lines.append(str(item["description"]))
                for achievement in item.get("achievements") or []:
                    text = (
                        achievement.get("text")
                        if isinstance(achievement, dict)
                        else achievement
                    )
                    lines.append(f"- {text}")
                if item.get("skills"):
                    lines.append(
                        "Skills: " + ", ".join(str(skill) for skill in item["skills"])
                    )
        elif kind == "synth_items":
            lines.append(f"## {_heading_of(kind, props)}")
            for entry in data:
                lines.append(f"### {str(entry.get('title') or '')}")
                if entry.get("description"):
                    lines.append(str(entry["description"]))
                for bullet in entry.get("bullets") or []:
                    text = bullet.get("text") if isinstance(bullet, dict) else bullet
                    lines.append(f"- {text}")
                labels = [
                    str(ref.get("label"))
                    for ref in entry.get("source_refs") or []
                    if isinstance(ref, dict) and ref.get("label")
                ]
                if labels:
                    lines.append("Based on: " + ", ".join(labels))
        elif kind == "skills":
            lines.append(f"## {_heading_of(kind, props)}")
            lines.append(
                ", ".join(
                    str(s.get("label") if isinstance(s, dict) else s) for s in data
                )
            )
        elif kind == "languages":
            lines.append(f"## {_heading_of(kind, props)}")
            lines.append(
                ", ".join(
                    _language_line(lang, props, snapshot)
                    if isinstance(lang, dict)
                    else str(lang)
                    for lang in data
                )
            )
        elif kind == "achievements":
            lines.append(f"## {_heading_of(kind, props)}")
            for item in data:
                head = " — ".join(
                    part
                    for part in (
                        str(item.get("title") or ""),
                        str(item.get("issuer") or ""),
                    )
                    if part
                )
                date_part = item.get("date") or ""
                lines.append(f"- {head}" + (f" ({date_part})" if date_part else ""))
        elif kind == "interests":
            lines.append(f"## {_heading_of(kind, props)}")
            lines.append(
                ", ".join(
                    str(i.get("label") if isinstance(i, dict) else i) for i in data
                )
            )
        elif kind == "custom_text":
            lines.append(f"## {props.get('title') or 'Custom'}")
            lines.append(str(data.get("text") or ""))
        elif kind == "letter":
            meta = " · ".join(
                str(props.get(field) or "")
                for field in ("recipient_name", "recipient_org", "date_label")
                if props.get(field)
            )
            if meta:
                lines.append(meta)
            if props.get("subject"):
                lines.append(f"**{props['subject']}**")
            lines.append(str(props.get("salutation") or ""))
            lines.extend(str(text) for text in data.get("paragraphs") or [])
            lines.append(str(props.get("closing") or ""))
            if props.get("show_signature", True):
                lines.append(str((snapshot.get("basics") or {}).get("name") or ""))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def to_ats_text(version_payload: dict) -> str:
    """Plain-text rendering in extraction order (ATS parsing parity)."""
    text = to_markdown(version_payload)
    text = re.sub(r"^#{1,6} ", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1: \2", text)
    text = re.sub(r"[*_`]", "", text)
    return text


_MD_RUN = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*")


def _add_inline_md_runs(paragraph: Any, text: str) -> None:
    """Append DOCX runs for **bold** / *italic*; links degrade to `text: url`."""
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1: \2", text)
    position = 0
    for match in _MD_RUN.finditer(text):
        if match.start() > position:
            paragraph.add_run(text[position : match.start()])
        if match.group(1) is not None:
            run = paragraph.add_run(match.group(1))
            run.bold = True
        else:
            run = paragraph.add_run(match.group(2))
            run.italic = True
        position = match.end()
    if position < len(text):
        paragraph.add_run(text[position:])


def to_docx(version_payload: dict, title: str) -> bytes:
    """DOCX from the compiled snapshot (python-docx, pure python)."""
    import io

    from docx import Document

    document = Document()
    snapshot = version_payload.get("snapshot") or {}
    blocks = version_payload.get("blocks") or []
    for kind, props, data in _visible_blocks(blocks, snapshot):
        if kind == "header":
            document.add_heading(str(data.get("name") or title), level=0)
            contact = " · ".join(
                str(data.get(field) or "")
                for field in ("headline", "email", "phone", "location")
                if data.get(field)
            )
            if contact:
                document.add_paragraph(contact)
            for link in data.get("links") or []:
                document.add_paragraph(_display_link(link))
        elif kind == "summary":
            document.add_heading(_heading_of(kind, props), level=1)
            document.add_paragraph(str(data.get("summary") or ""))
        elif kind == "items":
            document.add_heading(_heading_of(kind, props), level=1)
            for item in data:
                period = _period(item)
                document.add_heading(
                    _item_head(item) + (f" ({period})" if period else ""), level=2
                )
                if item.get("description"):
                    document.add_paragraph(str(item["description"]))
                for achievement in item.get("achievements") or []:
                    text = (
                        achievement.get("text")
                        if isinstance(achievement, dict)
                        else achievement
                    )
                    document.add_paragraph(str(text), style="List Bullet")
                if item.get("skills"):
                    document.add_paragraph(
                        "Skills: " + ", ".join(str(skill) for skill in item["skills"])
                    )
        elif kind == "synth_items":
            document.add_heading(_heading_of(kind, props), level=1)
            for entry in data:
                document.add_heading(str(entry.get("title") or ""), level=2)
                if entry.get("description"):
                    document.add_paragraph(str(entry["description"]))
                for bullet in entry.get("bullets") or []:
                    text = bullet.get("text") if isinstance(bullet, dict) else bullet
                    document.add_paragraph(str(text), style="List Bullet")
                labels = [
                    str(ref.get("label"))
                    for ref in entry.get("source_refs") or []
                    if isinstance(ref, dict) and ref.get("label")
                ]
                if labels:
                    document.add_paragraph("Based on: " + ", ".join(labels))
        elif kind == "skills":
            document.add_heading(_heading_of(kind, props), level=1)
            document.add_paragraph(
                ", ".join(
                    str(s.get("label") if isinstance(s, dict) else s) for s in data
                )
            )
        elif kind == "languages":
            document.add_heading(_heading_of(kind, props), level=1)
            document.add_paragraph(
                ", ".join(
                    _language_line(lang, props, snapshot)
                    if isinstance(lang, dict)
                    else str(lang)
                    for lang in data
                )
            )
        elif kind == "achievements":
            document.add_heading(_heading_of(kind, props), level=1)
            for item in data:
                head = " — ".join(
                    part
                    for part in (
                        str(item.get("title") or ""),
                        str(item.get("issuer") or ""),
                    )
                    if part
                )
                date_part = item.get("date") or ""
                document.add_paragraph(
                    head + (f" ({date_part})" if date_part else ""),
                    style="List Bullet",
                )
        elif kind == "interests":
            document.add_heading(_heading_of(kind, props), level=1)
            document.add_paragraph(
                ", ".join(
                    str(i.get("label") if isinstance(i, dict) else i) for i in data
                )
            )
        elif kind == "custom_text":
            document.add_heading(str(props.get("title") or "Custom"), level=1)
            for block_kind, items in custom_text_blocks(str(data.get("text") or "")):
                if block_kind == "ul":
                    for item in items:
                        paragraph = document.add_paragraph(style="List Bullet")
                        _add_inline_md_runs(paragraph, item)
                else:
                    paragraph = document.add_paragraph()
                    _add_inline_md_runs(paragraph, items[0])
        elif kind == "letter":
            for field in ("recipient_name", "recipient_org", "date_label"):
                if props.get(field):
                    document.add_paragraph(str(props[field]))
            if props.get("subject"):
                paragraph = document.add_paragraph()
                run = paragraph.add_run(str(props["subject"]))
                run.bold = True
            document.add_paragraph(str(props.get("salutation") or ""))
            for text in data.get("paragraphs") or []:
                paragraph = document.add_paragraph()
                _add_inline_md_runs(paragraph, str(text))
            document.add_paragraph(str(props.get("closing") or ""))
            if props.get("show_signature", True):
                document.add_paragraph(
                    str((snapshot.get("basics") or {}).get("name") or "")
                )
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def to_json_export(cv: CvDocument, version: CvVersion) -> bytes:
    """Portable JSON of the version."""
    package = {
        "kind": "career_assistant.cv_export",
        "version": 1,
        "title": cv.title,
        "language": cv.language,
        "content": version.content,
        "context_resolution": version.context_resolution,
        "content_hash": version.content_hash,
        "exported_at": version.created_at.isoformat(),
    }
    return json.dumps(package, indent=2, sort_keys=True).encode()


def _render_order(blocks: list[dict], template: object | None) -> list[dict]:
    """Blocks in the order the renderer emits their headings.

    A sidebar layout renders the sidebar column before (side=left) or
    after (side=right) the main flow — the section-order lint must
    compare against that reading order, not the stored block order.
    Single layouts (or sidebar layouts with no sidebar-assigned block —
    the renderer flattens those) keep the stored order."""
    layout, side = "single", "left"
    if template is not None:
        try:
            from app.schemas.cv_template import TemplateContent

            design = TemplateContent.model_validate(template.content).design
            layout, side = design.layout, design.sidebar_side
        except Exception:  # noqa: BLE001 — lint never fails on a bad row
            pass
    if layout != "sidebar":
        return blocks
    sidebar = [block for block in blocks if block_area(block) == "sidebar"]
    if not sidebar:
        return blocks
    main = [block for block in blocks if block_area(block) != "sidebar"]
    return sidebar + main if side == "left" else main + sidebar


def lint(
    version_payload: dict,
    html: str,
    metrics: dict,
    template: object | None,
) -> dict:
    """Deterministic ATS lint (no AI): structure, order, extractability."""
    snapshot = version_payload.get("snapshot") or {}
    blocks = version_payload.get("blocks") or []
    checks: list[dict] = []

    def add(check_id: str, level: str, message: str) -> None:
        checks.append({"id": check_id, "level": level, "message": message})

    basics = snapshot.get("basics") or {}
    if not basics.get("name"):
        add("contact_name", "fail", "No name in the header.")
    if not basics.get("email"):
        add("contact_email", "fail", "No email in the header — ATS contact match.")
    if not basics.get("phone"):
        add("contact_phone", "warn", "No phone number in the header.")

    expected = [
        _heading_of(kind, props).strip().lower()
        for kind, props, _data in _visible_blocks(
            _render_order(blocks, template), snapshot
        )
        if kind not in ("header", "letter")
    ]
    rendered = [
        re.sub(r"<[^>]+>", "", match).strip().lower()
        for match in re.findall(r"<h2[^>]*>(.*?)</h2>", html, flags=re.DOTALL)
    ]
    if rendered != expected:
        add(
            "section_order",
            "fail",
            "Rendered section order deviates from block order — extraction "
            "would reorder content.",
        )
    else:
        add("section_order", "pass", "Section order matches reading order.")
    non_standard = [heading for heading in expected if heading not in STANDARD_HEADINGS]
    if non_standard:
        add(
            "standard_headings",
            "warn",
            "Non-standard heading(s): " + ", ".join(sorted(non_standard)),
        )
    for source_key in ("experience", "projects", "volunteer"):
        for item in snapshot.get(source_key) or []:
            if not item.get("start"):
                add(
                    "experience_dates",
                    "warn",
                    f"A {source_key} item has no start date.",
                )
                break
    if len(str(snapshot.get("summary") or "")) > 600:
        add("summary_length", "info", "Summary exceeds ~600 characters.")
    for kind, props, data in _visible_blocks(blocks, snapshot):
        if kind != "letter":
            continue
        words = sum(len(str(text).split()) for text in data.get("paragraphs") or [])
        if words > 400:
            add(
                "letter_length",
                "warn",
                f"Cover letter runs ~{words} words — aim for under 400.",
            )
        elif words < 80:
            add(
                "letter_length",
                "info",
                f"Cover letter is only ~{words} words — one more grounded "
                "paragraph usually helps.",
            )
        else:
            add("letter_length", "pass", "Cover letter length is in the sweet spot.")
    if metrics.get("overflow"):
        add(
            "page_overflow",
            "warn",
            f"Estimated at {metrics.get('estimated_pages')} pages vs the "
            f"{metrics.get('max_pages')}-page budget — the estimate drifts on "
            "dense layouts; the measured count (when the PDF engine is "
            "available) is authoritative.",
        )
    ats_safe = getattr(template, "ats_safe", None)
    if ats_safe is False:
        add(
            "template_ats_safe",
            "warn",
            "The chosen template is not flagged ATS-safe (decorative layout).",
        )
    if (version_payload.get("design") or {}).get("section_style") == "card":
        add(
            "card_sections",
            "info",
            "Card-style section containers may confuse some ATS parsers.",
        )
    levels = [check["level"] for check in checks]
    score = 100 - 20 * levels.count("fail") - 8 * levels.count("warn")
    return {
        "score": max(0, score),
        "passed": not any(check["level"] == "fail" for check in checks),
        "checks": checks,
        "metrics": metrics,
    }


class CvExportService:
    """Compile + serialize one CV into a downloadable artifact."""

    def __init__(self, db):
        self.builder = CvBuilderService(db)

    async def _stamp_pages_actual(self, version, actual: int, max_pages: int) -> None:
        """Reconcile the measured PDF page count onto the exported version.

        Every export compiles a version first; stamping `render.pages_actual`
        right after gives lint (and later, reconciliation surfaces) the real
        print extent instead of the estimate.
        """
        from sqlalchemy.orm.attributes import flag_modified

        content = dict(version.content or {})
        content["render"] = {
            **(content.get("render") or {}),
            "pages_actual": actual,
            "over_budget": actual > max_pages,
        }
        version.content = content
        flag_modified(version, "content")
        await self.builder.cvs.db.commit()

    async def export(self, cv: CvDocument, fmt: str) -> ExportFile:
        """Compile (auto-version) then serialize in the requested format."""
        if fmt not in MEDIA_TYPES:
            raise ValidationError(f"Unknown export format: {fmt}")
        version, html, _metrics = await self.builder.compile(
            cv, created_by=CvVersionCreator.EXPORT
        )
        filename = f"{slugify(cv.title)}.{EXTENSIONS[fmt]}"
        if fmt == "pdf":
            try:
                pdf = await html_to_pdf(html)
            except PDFEngineUnavailable:
                raise
            actual = count_pdf_pages(pdf)
            if actual is not None:
                await self._stamp_pages_actual(version, actual, cv.max_pages)
            return ExportFile(filename, MEDIA_TYPES[fmt], pdf, False)
        if fmt == "docx":
            return ExportFile(
                filename, MEDIA_TYPES[fmt], to_docx(version.content, cv.title), False
            )
        if fmt == "md":
            return ExportFile(
                filename, MEDIA_TYPES[fmt], to_markdown(version.content).encode(), False
            )
        if fmt == "ats_text":
            return ExportFile(
                filename, MEDIA_TYPES[fmt], to_ats_text(version.content).encode(), False
            )
        return ExportFile(
            filename, MEDIA_TYPES[fmt], to_json_export(cv, version), False
        )

    async def lint_report(self, cv: CvDocument) -> dict:
        """Deterministic lint over the current state (no version created).

        When the PDF engine is present the page count is MEASURED live by
        printing the current state — renderer estimates drift (especially
        for dense two-column layouts), and the polish gate must judge the
        truth. A live measure always beats the last export's stamp (which
        ages with every edit); the stamp only speaks when no engine can.
        """
        html, payload, resolution, metrics = await self.builder.render_state(cv)
        report = lint(
            payload, html, asdict(metrics), await self.builder.template_row(cv)
        )
        report["resolved_items"] = len(resolution.items)
        report["checks"].extend(await self._synth_checks(cv, resolution))
        actual, source = await self._live_measure(cv, html)
        if actual is None:
            actual = await self._measured_pages(cv)
            source = "last_export" if actual is not None else None
        report["metrics"]["page_count_source"] = source
        if actual is not None:
            report["metrics"]["pages_actual"] = actual
            report["metrics"]["pages_actual_over_budget"] = actual > cv.max_pages
            if actual > cv.max_pages:
                report["checks"].append(
                    {
                        "id": "page_budget",
                        "level": "fail",
                        "message": (
                            f"Measured {actual} pages exceed the {cv.max_pages}-page "
                            "budget — densify (update_design) or trim; the "
                            "budget never grows."
                        ),
                    }
                )
        return report

    async def _synth_checks(self, cv: CvDocument, resolution) -> list[dict]:
        """Plan-62 synth signals (deterministic, no AI): availability,
        staleness and override conflicts over the resolved state."""
        import uuid

        from app.schemas.cv import CvContextSelection
        from app.services.cv_synth_service import (
            CvSynthService,
            _context_index,
        )

        synth = CvSynthService(self.builder.cvs.db)
        selection = (
            CvContextSelection.model_validate(cv.context)
            if cv.context
            else CvContextSelection()
        )
        checks: list[dict] = []

        def add(cid: str, level: str, message: str, **extra: object) -> None:
            entry = {"id": cid, "level": level, "message": message}
            entry.update(extra)
            checks.append(entry)

        pins = selection.synth_pins
        ref_by_id: dict[str, str] = {}
        for key, ids in resolution.snapshot_index.items():
            for item_id in ids:
                ref_by_id.setdefault(item_id, key)
        matches = await synth.match_for_cv(
            cv, refs=[(key, item_id) for item_id, key in ref_by_id.items()]
        )

        # Pin honesty (plan 83 follow-up): a starred variant that is not
        # rendering must say WHY — silent no-ops read as "variants are
        # broken" (draft not yet activated, archived by a newer
        # activation, language/posting gated out, or deleted).
        trace: dict[str, str] = resolution.synth_applied or {}
        for ref_key, synth_id in (pins or {}).items():
            if ref_key in trace:
                continue
            reason: str | None = None
            try:
                row = await synth.get_owned(uuid.UUID(synth_id), cv.user_id)
            except ValueError:
                reason = "the pin is malformed"
            except Exception:  # noqa: BLE001 — missing/foreign variant
                reason = "the pinned variant no longer exists"
            if reason is None:
                if row.status != CvSynthStatus.ACTIVE.value:
                    reason = (
                        f"the pinned variant is a {row.status} — activate it "
                        "to use it here"
                    )
                elif row.voice.get("language") != cv.language:
                    reason = (
                        "the pinned variant is "
                        f"{row.voice.get('language') or 'unlabeled'}, this CV "
                        f"renders in {cv.language or 'en'}"
                    )
                elif (
                    row.target_posting_id is not None
                    and row.target_posting_id != cv.target_posting_id
                ):
                    reason = "the pinned variant targets another posting"
            if reason is not None:
                add(
                    "synth_pin_inactive",
                    "warn",
                    f"Starred variant for {ref_key} is not used: {reason}.",
                    ref=ref_key,
                )

        unpinned = {
            ref: variant
            for ref, variant in matches.items()
            if not pins or str(pins.get(f"{ref[0]}:{ref[1]}", "")) != str(variant.id)
        }
        if unpinned:
            add(
                "synth_available",
                "info",
                f"{len(unpinned)} matching synthesized variant(s) exist — "
                "star one on this CV to use it.",
                count=len(unpinned),
            )
            return checks

        add(
            "synth_share",
            "pass",
            f"{len(trace)} rendered item(s) use synthesized variants.",
            applied=len(trace),
        )
        context = await _context_index(self.builder.cvs.db, cv.user_id)
        for synth_id in dict.fromkeys(trace.values()):
            row = await synth.get_owned(uuid.UUID(synth_id), cv.user_id)
            if synth._state_of(row, context)["stale"]:
                ref_key = (
                    f"{row.source_refs[0]['source_key']}:"
                    f"{row.source_refs[0]['item_id']}"
                )
                add(
                    "synth_stale",
                    "warn",
                    f"Synthesized variant for {ref_key} tracks an edited "
                    "source — regenerate or review.",
                    ref=ref_key,
                )
        overrides: dict[str, dict] = (cv.working_content or {}).get("overrides") or {}
        for ref, patch in overrides.items():
            if isinstance(patch, dict) and patch and ref in trace:
                add(
                    "synth_conflict",
                    "info",
                    f"Manual override beats the synthesized variant for {ref}.",
                    ref=ref,
                )
        return checks

    async def _live_measure(
        self, cv: CvDocument, html: str
    ) -> tuple[int | None, str | None]:
        """Real page count of the current state, printed through the engine.

        The measure prints the exact HTML an export would produce, so the
        count includes margins and CSS print fragmentation. Attempted
        ungated — probing availability separately would double-launch the
        engine for one lint call.
        """
        try:
            measure = await measure_pages(html, page_size=cv.page_size, max_images=0)
        except PDFEngineUnavailable:
            return None, None
        except Exception:  # noqa: BLE001 — engine missing/flaky → estimate stays
            return None, None
        return measure.pages, measure.source

    async def _measured_pages(self, cv: CvDocument) -> int | None:
        """The real page count record from the CV's latest PDF export.

        Estimates drift; measured exports don't. When any PDF export of
        this CV stamped its actual page count (as exported to PDF), lint
        reports it next to the estimate so the two can be compared.
        """
        from sqlalchemy import select

        from app.models.cv_model import CvVersion

        rows = await self.builder.cvs.db.execute(
            select(CvVersion.content)
            .where(CvVersion.cv_document_id == cv.id)
            .order_by(CvVersion.version.desc())
            .limit(5)
        )
        for row in reversed(rows.scalars().all()):
            stamped = (row or {}).get("render", {}).get("pages_actual")
            if stamped is not None:
                return int(stamped)
        return None


__all__ = [
    "ExportFormat",
    "ExportFile",
    "CvExportService",
    "lint",
    "to_markdown",
    "to_ats_text",
    "to_docx",
    "to_json_export",
    "slugify",
]
