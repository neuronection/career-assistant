"""Deterministic CV renderer: the ONLY render path.

Pure function of (template content, context snapshot, options) →
print-ready HTML + layout metrics. Same inputs always produce byte-equal
output (preview, exports, and visual-review all share this path). Page
margins live in `@page` for print and are mirrored onto `body` in
`@media screen` so previews show the exact content box the PDF gets.
All interpolated values are HTML-escaped; the output never references
external assets (CSP-safe: no fonts, scripts, or images fetched from the
network).
"""

import html
import math
import re
from dataclasses import dataclass, field
from typing import Any

from app.models.enums import CvOverflowPolicy, CvPageSize
from app.schemas.cv_template import DesignTokens, TemplateContent
from app.services.cv_blocks import block_area, validate_blocks
from app.services.cv_languages import is_proficiency_cert, proficiency_for

FONT_STACKS = {
    "sans": "-apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    "serif": "Georgia, 'Times New Roman', serif",
    "mixed": None,  # headings serif, body sans
    "geometric": "'Century Gothic', 'Avenir Next', 'Futura', Verdana, sans-serif",
}

DATE_FORMATS = {"mon_yyyy", "iso", "eu", "year"}

SOURCE_DEFAULT_TITLES = {
    "experience": "Work Experience",
    "education": "Education",
    "certifications": "Certifications",
    "projects": "Projects",
    "volunteer": "Volunteering",
}

MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]

PAGE_MM = {"a4": (210, 297), "letter": (216, 279)}
DENSITY_MARGIN_MM = {"compact": 8, "normal": 12, "roomy": 16}


def _page_margin_mm(design: DesignTokens) -> int:
    """Effective page margin: explicit template override, else density default."""
    if design.margin_mm is not None:
        return design.margin_mm
    return DENSITY_MARGIN_MM[design.density]


def esc(value: Any) -> str:
    """HTML-escape any interpolated value (never trust content)."""
    return html.escape(str(value if value is not None else ""), quote=True)


def inline_md(value: Any) -> str:
    """Escape, then apply the minimal inline markup: **bold**, *italic*,
    [text](https://url|mailto:…). Everything else stays literal text."""
    text = esc(value)
    while True:
        strong = re.search(r"\*\*(.+?)\*\*", text)
        if strong:
            text = (
                text[: strong.start()]
                + f"<strong>{strong.group(1)}</strong>"
                + text[strong.end() :]
            )
            continue
        em = re.search(r"\*(.+?)\*", text)
        if em:
            text = text[: em.start()] + f"<em>{em.group(1)}</em>" + text[em.end() :]
            continue
        break
    return _MD_LINK.sub(r'<a href="\2">\1</a>', text)


_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+|mailto:[^)\s]+)\)")

_SAFE_URL = re.compile(r"^(https?://|mailto:|tel:)", re.IGNORECASE)


def _short_url(url: str) -> str:
    """Printable link address: no scheme, no www, no query/fragment."""
    short = re.sub(r"^[a-z][a-z0-9+.-]*://", "", url.strip(), flags=re.I)
    short = re.sub(r"^www\.", "", short, flags=re.I)
    short = short.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return short


def _display_link(link: dict) -> str:
    """Print-first link text: the address must be legible on paper.

    Custom labels are kept as a prefix when they add something (they
    never replace the address); a plain `kind` icon + "Github" chip is
    not useful when nothing is clickable, so the URL always shows.
    """
    short = _short_url(str(link.get("url") or ""))
    label = str(link.get("label") or "").strip()
    if label and label.lower() != short.lower() and label.lower() not in short.lower():
        return f"{label} ({short})"
    return short


def _safe_href(url: Any) -> str | None:
    """Scheme-allowlisted href for user-supplied URLs (never trust content)."""
    value = str(url or "").strip()
    return value if _SAFE_URL.match(value) else None


def custom_text_blocks(text: str) -> list[tuple[str, list[str]]]:
    """Split custom text into renderable blocks.

    Blank lines separate paragraphs; consecutive lines starting with
    "- " group into one bullet list. Returns ("p", [line]) and
    ("ul", [items]) pairs so every export shares one structure.
    """
    blocks: list[tuple[str, list[str]]] = []
    bullets: list[str] = []

    def flush() -> None:
        nonlocal bullets
        if bullets:
            blocks.append(("ul", bullets))
            bullets = []

    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith("- ") or line.startswith("* "):
            bullets.append(line[2:])
            continue
        flush()
        blocks.append(("p", [line]))
    flush()
    return blocks


def format_period(start: Any, end: Any, date_format: str = "mon_yyyy") -> str:
    """Deterministic period label in the requested date format."""

    def side(raw: Any) -> str:
        text = str(raw or "").strip()
        if not text:
            return ""
        parts = text.split("-")
        if len(parts) == 2 and parts[0].isdigit() and len(parts[0]) == 4:
            year, month = parts[0], parts[1]
            if month.isdigit() and 1 <= int(month) <= 12:
                if date_format == "iso":
                    return f"{year}-{month}"
                if date_format == "eu":
                    return f"{month}/{year}"
                if date_format == "year":
                    return year
                return f"{MONTHS[int(month) - 1]} {year}"
            return year
        return text

    start_label, end_label = side(start), side(end or "")
    if start_label and end_label:
        return f"{start_label} – {end_label}"
    return start_label or end_label


@dataclass
class RenderMetrics:
    """Heuristic layout metrics backing the deterministic lint.

    Estimates are deliberately conservative; they power overflow/empty
    detection without a rendering engine.
    """

    estimated_lines: int = 0
    lines_per_page: int = 0
    estimated_pages: int = 1
    empty_blocks: list[str] = field(default_factory=list)
    truncated: int = 0
    overflow: bool = False


@dataclass
class RenderResult:
    html: str
    metrics: RenderMetrics


def _lines_per_page(design: DesignTokens, page_size: str) -> int:
    width_mm, height_mm = PAGE_MM[page_size]
    usable = height_mm - 2 * _page_margin_mm(design)
    line_mm = design.base_size_pt * 0.3528 * design.line_height
    return max(20, int(usable / line_mm))


def _chars_per_line(
    design: DesignTokens, page_size: str, width_share: float = 1.0
) -> int:
    """Average characters one text line holds at the current geometry.

    `width_share` narrows the estimate for sidebar columns; ~0.48em per
    char is a conservative average for the font stacks in use.
    """
    width_mm, _ = PAGE_MM[page_size]
    usable_width = (width_mm - 2 * _page_margin_mm(design)) * max(
        0.1, min(width_share, 1.0)
    )
    char_mm = design.base_size_pt * 0.3528 * 0.48
    return max(20, int(usable_width / char_mm))


def _wrap_lines(text: str, chars_per_line: int) -> int:
    stripped = (text or "").strip()
    return math.ceil(len(stripped) / chars_per_line) if stripped else 0


def _pages_for(main_lines: int, sidebar_lines: int, lpp: int, two_columns: bool) -> int:
    """Page extent from per-column line costs.

    Columns flow independently side by side, so a true two-column
    layout fills max(main, sidebar) pages — not the sum — while a
    single-column layout stacks everything into one flow.
    """
    if not two_columns:
        return max(1, math.ceil((main_lines + sidebar_lines) / lpp))
    main_pages = max(1, math.ceil(main_lines / lpp)) if main_lines else 1
    sidebar_pages = max(1, math.ceil(sidebar_lines / lpp)) if sidebar_lines else 1
    return max(main_pages, sidebar_pages)


def _block_lines(
    kind: str,
    props: Any,
    snapshot: dict,
    design: DesignTokens,
    page_size: str = CvPageSize.A4.value,
    width_share: float = 1.0,
) -> int:
    """Estimated line cost of one block from the snapshot.

    Column-aware (a sidebar block wraps ~3× sooner than the main
    column) so shrink/truncate fire on the content that actually
    overflows — long item descriptions were previously free.
    """
    chars = _chars_per_line(design, page_size, width_share)
    if kind == "header":
        basics = snapshot.get("basics") or {}
        lines = 2
        if getattr(design, "show_photo", False) and basics.get("photo"):
            lines += max(0, int(design.photo_size_mm / (design.base_size_pt * 0.3528)))
        contact = " ".join(
            str(basics.get(field) or "") for field in ("email", "phone", "location")
        ) + " ".join(
            _display_link(link) if isinstance(link, dict) else ""
            for link in basics.get("links") or []
        )
        return lines + _wrap_lines(contact, chars)
    if kind == "summary":
        return _wrap_lines(str(snapshot.get("summary") or ""), chars) + 1
    if kind == "items":
        items = _ordered_by_props(snapshot.get(props.source_key) or [], props)
        lines = 1
        for item in items[: props.max_items]:
            lines += 2  # head + spacing
            detail = str(item.get("description") or item.get("detail") or "").strip()
            if props.show_description and detail:
                lines += _wrap_lines(detail, chars)
            for achievement in (item.get("achievements") or [])[:5]:
                text = (
                    str(achievement.get("text") or "")
                    if isinstance(achievement, dict)
                    else str(achievement or "")
                )
                lines += max(1, _wrap_lines(text, chars))
        return lines
    if kind == "synth_items":
        entries = snapshot.get("synth") or []
        selected_ids = getattr(props, "selected", None) or []
        if selected_ids:
            chosen = {str(item_id) for item_id in selected_ids}
            entries = [
                entry
                for entry in entries
                if isinstance(entry, dict) and str(entry.get("id")) in chosen
            ]
        lines = 1
        for entry in entries[: props.max_items]:
            lines += 2
            detail = str(entry.get("description") or "").strip()
            if detail:
                lines += _wrap_lines(detail, chars)
            for bullet in (entry.get("bullets") or [])[:8]:
                lines += max(1, _wrap_lines(str(bullet), chars))
            if props.show_source_chips:
                lines += 1
        return lines
    if kind == "skills":
        skill_rows = snapshot.get("skills") or []
        selected_ids = getattr(props, "selected", None) or []
        if selected_ids:
            chosen = {str(x) for x in selected_ids}
            skill_rows = [
                s
                for s in skill_rows
                if isinstance(s, dict) and str(s.get("id") or "") in chosen
            ]
        count = min(len(skill_rows), props.max_items)
        chips_per_row = max(2, chars // 14)
        return math.ceil(count / chips_per_row) + 1
    if kind == "languages":
        count = 1 if snapshot.get("languages") else 0
        extra = 0
        if getattr(props, "show_proficiency", False):
            certifications = snapshot.get("certifications") or []
            extra += len(
                proficiency_for(snapshot.get("languages") or [], certifications)
            )
        if getattr(props, "display", "chips") == "list":
            count = min(len(snapshot.get("languages") or []), 8) + extra
        return math.ceil(count / max(2, chars // 16)) + 1
    if kind == "achievements":
        achievements = snapshot.get("achievements") or []
        lines = 1
        for achievement in achievements[:10]:
            text = (
                str(achievement.get("title") or "")
                if isinstance(achievement, dict)
                else ""
            )
            lines += max(1, _wrap_lines(text, chars))
        return lines
    if kind == "interests":
        count = min(len(snapshot.get("interests") or []), props.max_items)
        return math.ceil(count / max(2, chars // 12)) + 1
    if kind == "custom_text":
        return _wrap_lines(str(props.text or ""), chars) + 1
    if kind == "letter":
        paragraphs = [str(p) for p in (props.paragraphs or []) if str(p).strip()]
        lines = sum(_wrap_lines(text, chars) for text in paragraphs) + 3
        if props.recipient_name or props.recipient_org:
            lines += 1
        if props.date_label:
            lines += 1
        return lines
    if kind == "spacer":
        return max(1, props.height_mm // 5)
    return 1


def _contact_line(basics: dict, props: Any, design: Any = None) -> str:
    from app.services.cv_icons import LINK_KIND_ICONS, icon

    show_icons = bool(getattr(design, "show_icons", False))

    def piece(name: str, text: str, url: str | None = None, css_class: str = "") -> str:
        mark = icon(name) if show_icons else ""
        body = esc(text)
        href = _safe_href(url) if url else None
        value = f'<a href="{esc(href)}">{body}</a>' if href else body
        css = f" {css_class}" if css_class else ""
        return f"<span class='cpi{css}'>{mark}{value}</span>"

    parts = []
    if basics.get("email"):
        email = str(basics["email"]).strip()
        parts.append(piece("mail", email, f"mailto:{email}"))
    if basics.get("phone"):
        phone = str(basics["phone"]).strip()
        parts.append(piece("phone", phone, "tel:" + re.sub(r"\s+", "", phone)))
    if props.show_location and basics.get("location"):
        parts.append(piece("location", basics["location"]))
    if props.show_links:
        for link in basics.get("links") or []:
            url = str(link.get("url") or "").strip()
            href = _safe_href(url)
            if not href:
                continue  # a scheme-unsafe URL is never printed as text
            display = _display_link(link)
            if display:
                parts.append(
                    piece(
                        LINK_KIND_ICONS.get(link.get("kind"), "link"),
                        display,
                        href,
                        css_class="lnk",
                    )
                )
    if show_icons:
        return "<span class='contact-icons'>" + " ".join(parts) + "</span>"
    return " <span class='sep'>·</span> ".join(parts)


def _ordered_by_props(items: list, props: Any) -> list:
    """Applies `props.order` (plan 72.1): the ordered ids print first,
    then the remainder in resolved order. Runs after the block's
    kind/proficiency filters and before `max_items` truncation, so the
    user's order decides what survives truncation."""
    order = list(getattr(props, "order", None) or [])
    if not order or not items:
        return items
    first = {str(item_id): rank for rank, item_id in enumerate(order)}
    if not any(str(item.get("id")) in first for item in items):
        return items
    head = [item for item in items if str(item.get("id")) in first]
    head.sort(key=lambda item: first[str(item.get("id"))])
    tail = [item for item in items if str(item.get("id")) not in first]
    return head + tail


def _render_items(items: list, props: Any) -> str:
    rows = []
    for item in _ordered_by_props(items, props)[: props.max_items]:
        title = esc(item.get("title") or item.get("program") or "")
        org = (
            esc(item.get("org") or item.get("institution") or item.get("issuer") or "")
            if props.show_org
            else ""
        )
        period = esc(
            format_period(
                item.get("start") or item.get("issued"),
                item.get("end"),
                props.date_format,
            )
        )
        head = f"<span class='item-title'>{title}</span>"
        if org:
            head += f" <span class='item-org'>{org}</span>"
        if period:
            head += f" <span class='item-period'>{period}</span>"
        fragments = [f"<li><div class='item-head'>{head}</div>"]
        detail = str(item.get("description") or item.get("detail") or "").strip()
        if detail and props.show_description:
            fragments.append(f"<p class='item-detail'>{inline_md(detail)}</p>")
        if props.show_achievements and item.get("achievements"):
            bullets = "".join(
                f"<li>{inline_md(a.get('text') if isinstance(a, dict) else a)}</li>"
                for a in item["achievements"][:5]
            )
            fragments.append(f"<ul class='ach'>{bullets}</ul>")
        if props.show_skills and item.get("skills"):
            chips = "".join(
                f"<span class='chip'>{esc(s)}</span>" for s in item["skills"][:8]
            )
            fragments.append(f"<div class='chips'>{chips}</div>")
        fragments.append("</li>")
        rows.append("".join(fragments))
    ul_class = (
        "items items-timeline"
        if getattr(props, "style", "list") == "timeline"
        else "items"
    )
    return f"<ul class='{ul_class}'>{''.join(rows)}</ul>"


def _container_of(props: Any, design: Any) -> tuple[str, str]:
    """Resolve a block's container to (css classes, inline style)."""
    container = getattr(props, "container", None) or _NoContainer()
    mode = getattr(container, "container", "inherit")
    base_mode = (
        mode
        if mode != "inherit"
        else ("card" if design.section_style == "card" else "flat")
    )
    classes: list[str] = ["cv-block"]
    styles: list[str] = []
    if base_mode in ("card", "tinted"):
        classes.append("cv-card")
        styles.append(
            f"background:{container.background or f'color-mix(in srgb, {design.accent_color} 6%, {design.background_color})'}"
        )
    if base_mode == "outline":
        classes.append("cv-outline")
        styles.append(
            f"border:0.4mm solid {container.border_color or design.border_color}"
        )
    if base_mode == "accent-bar":
        classes.append("cv-accentbar")
        styles.append(
            f"border-left:1mm solid {container.border_color or design.accent_color}"
        )
    if container.radius is not None:
        styles.append(f"border-radius:{container.radius}mm")
    elif base_mode in ("card", "tinted", "outline", "accent-bar"):
        styles.append(f"border-radius:{design.corner_radius}mm")
    if container.padding_mm is not None:
        styles.append(f"padding:{container.padding_mm}mm")
    elif base_mode in ("card", "tinted", "outline", "accent-bar"):
        styles.append("padding:2.5mm 3.5mm")
    style = ";".join(styles)
    return " ".join(classes), f" style='{esc(style)}'" if style else ""


class _NoContainer:
    container = "inherit"
    background = None
    border_color = None
    radius = None
    padding_mm = None


def _section_tag(
    kind: str, title: str, body: str, design: Any, props: Any = None
) -> str:
    """Wrap a section body with the resolved container style."""
    classes, style = (
        _container_of(props, design) if props is not None else ("cv-block", "")
    )
    heading = f"<h2>{esc(title)}</h2>" if title else ""
    return f"<section class='{classes}'{style}>{heading}{body}</section>"


def _render_block(
    kind: str, props: Any, snapshot: dict, design: Any = None
) -> tuple[str, bool]:
    """Returns (html, had_content) — empty blocks hide by default."""
    design = design or DesignTokens()
    if kind == "header":
        basics = snapshot.get("basics") or {}
        headline = esc(basics.get("headline") or "")
        contact = _contact_line(basics, props, design)
        photo = ""
        if design.show_photo and basics.get("photo"):
            radius = {"circle": "50%", "rounded": "3mm", "square": "0"}[
                design.photo_shape
            ]
            photo = (
                f"<img class='cv-photo' src='{esc(basics['photo'])}' alt='' "
                f"style='width:{design.photo_size_mm}mm;height:{design.photo_size_mm}mm;"
                f"border-radius:{radius}'/>"
            )
        inner = (
            f"<h1>{esc(basics.get('name') or '')}</h1>"
            + (f"<p class='headline'>{headline}</p>" if headline else "")
            + (f"<p class='contact'>{contact}</p>" if contact else "")
        )
        body = (
            f"<div class='cv-header-row'>{photo}<div class='cv-header-main'>{inner}</div></div>"
            if photo
            else inner
        )
        return (
            f"<header class='cv-header'>{body}</header>",
            bool(basics.get("name")),
        )
    if kind == "summary":
        text = str(snapshot.get("summary") or "")[: props.max_chars]
        if not text:
            return "", False
        return (
            _section_tag(
                "summary",
                props.title,
                f"<p class='summary'>{inline_md(text)}</p>",
                design,
                props,
            ),
            True,
        )
    if kind == "items":
        items = snapshot.get(props.source_key) or []
        if props.kinds:
            items = [item for item in items if item.get("kind") in props.kinds]
        if props.exclude_proficiency:
            items = [item for item in items if not is_proficiency_cert(item)]
        if not items:
            return "", False
        title = props.title or SOURCE_DEFAULT_TITLES.get(
            props.source_key, props.source_key
        )
        return (
            _section_tag("items", title, _render_items(items, props), design, props),
            True,
        )
    if kind == "synth_items":
        entries = snapshot.get("synth") or []
        selected_ids = getattr(props, "selected", None) or []
        if selected_ids:
            chosen = {str(item_id) for item_id in selected_ids}
            entries = [
                entry
                for entry in entries
                if isinstance(entry, dict) and str(entry.get("id")) in chosen
            ]
        entries = entries[: props.max_items]
        if not entries:
            return "", False
        rows = []
        for entry in entries:
            head = f"<span class='item-title'>{esc(entry.get('title') or '')}</span>"
            fragments = [f"<li><div class='item-head'>{head}</div>"]
            detail = str(entry.get("description") or "").strip()
            if detail:
                fragments.append(f"<p class='item-detail'>{inline_md(detail)}</p>")
            bullets = [
                text.get("text") if isinstance(text, dict) else text
                for text in entry.get("bullets") or []
            ]
            if bullets:
                bullet_html = "".join(
                    f"<li>{inline_md(str(text))}</li>" for text in bullets[:8]
                )
                fragments.append(f"<ul class='ach'>{bullet_html}</ul>")
            if props.show_source_chips:
                chips = "".join(
                    f"<span class='chip'>{esc(str(ref.get('label') or ref.get('item_id') or ''))}</span>"
                    for ref in entry.get("source_refs") or []
                    if isinstance(ref, dict)
                )
                if chips:
                    fragments.append(f"<div class='chips'>{chips}</div>")
            fragments.append("</li>")
            rows.append("".join(fragments))
        return (
            _section_tag(
                "synth_items",
                props.title,
                f"<ul class='items'>{''.join(rows)}</ul>",
                design,
                props,
            ),
            True,
        )
    if kind == "skills":
        skills = snapshot.get("skills") or []
        if not skills:
            return "", False
        selected_ids = getattr(props, "selected", None) or []
        if selected_ids:
            chosen = {str(x) for x in selected_ids}
            skills = [
                s
                for s in skills
                if isinstance(s, dict) and str(s.get("id") or "") in chosen
            ]
            if not skills:
                return "", False
        shown = skills[: props.max_items]
        if props.display == "list":
            body = (
                "<ul class='items'>"
                + "".join(
                    f"<li>{esc(s.get('label') or s)}"
                    + (
                        f" <span class='item-period'>level {s['level']}/10</span>"
                        if props.show_levels and isinstance(s, dict) and s.get("level")
                        else ""
                    )
                    + "</li>"
                    for s in shown
                )
                + "</ul>"
            )
        elif props.display == "bars":
            rows = []
            for skill in shown:
                label = esc(skill.get("label") if isinstance(skill, dict) else skill)
                level = skill.get("level") if isinstance(skill, dict) else None
                pct = max(0, min(100, int((level or 0) * 10)))
                rows.append(
                    f"<div class='bar-row'><span class='bar-label'>{label}</span>"
                    f"<span class='bar'><span class='bar-fill' style='width:{pct}%'></span></span></div>"
                )
            body = "<div class='bars'>" + "".join(rows) + "</div>"
        else:
            body = (
                "<div class='chips'>"
                + "".join(
                    f"<span class='chip'>{esc(s.get('label') if isinstance(s, dict) else s)}{'' if not (props.show_levels and isinstance(s, dict) and s.get('level')) else f' <em>{s['level']}/10</em>'}</span>"
                    for s in shown
                )
                + "</div>"
            )
        return _section_tag("skills", props.title, body, design, props), True
    if kind == "languages":
        languages = snapshot.get("languages") or []
        if not languages:
            return "", False
        proficiency = (
            proficiency_for(languages, snapshot.get("certifications") or [])
            if props.show_proficiency
            else {}
        )

        def _entry(lang: Any) -> dict:
            return lang if isinstance(lang, dict) else {"label": str(lang)}

        def _text(entry: dict) -> str:
            label = esc(entry.get("label") or entry.get("code") or "")
            level = esc(entry.get("level", ""))
            text = f"{label} — {level}" if level else label
            if props.show_cefr and entry.get("cefr"):
                text = f"{text} ({esc(entry['cefr'])})"
            if props.show_proficiency:
                cert = proficiency.get(entry.get("code") or "")
                if cert:
                    issued = esc(cert.get("start") or "")
                    text = f"{text} · {esc(cert.get('title') or '')}" + (
                        f", {issued}" if issued else ""
                    )
            return text

        entries = [_entry(lang) for lang in languages]
        if props.display == "list":
            body = (
                "<ul class='items'>"
                + "".join(f"<li>{_text(e)}</li>" for e in entries)
                + "</ul>"
            )
        else:
            body = (
                "<div class='chips'>"
                + "".join(f"<span class='chip'>{_text(e)}</span>" for e in entries)
                + "</div>"
            )
        return (
            _section_tag("languages", props.title, body, design, props),
            True,
        )
    if kind == "achievements":
        achievements = snapshot.get("achievements") or []
        allowed = [
            a
            for a in achievements
            if not props.kinds or (a.get("kind") or "award") in props.kinds
        ]
        if not allowed:
            return "", False
        rows = "".join(
            f"<li><span class='item-title'>{esc(a.get('title') or a)}</span>"
            + (
                f" <span class='item-org'>{esc(a['issuer'])}</span>"
                if a.get("issuer")
                else ""
            )
            + (
                f" <span class='item-period'>{esc(a.get('date', ''))}</span>"
                if a.get("date")
                else ""
            )
            + "</li>"
            for a in allowed[:10]
        )
        return (
            _section_tag(
                "achievements",
                props.title,
                f"<ul class='items'>{rows}</ul>",
                design,
                props,
            ),
            True,
        )
    if kind == "interests":
        interests = snapshot.get("interests") or []
        if not interests:
            return "", False
        chips = "".join(
            f"<span class='chip'>{esc(i.get('label') if isinstance(i, dict) else i)}</span>"
            for i in interests[: props.max_items]
        )
        return (
            _section_tag(
                "interests",
                props.title,
                f"<div class='chips'>{chips}</div>",
                design,
                props,
            ),
            True,
        )
    if kind == "custom_text":
        if not str(props.text).strip():
            return "", False
        body = "".join(
            "<ul>" + "".join(f"<li>{inline_md(item)}</li>" for item in items) + "</ul>"
            if block_kind == "ul"
            else f"<p>{inline_md(items[0])}</p>"
            for block_kind, items in custom_text_blocks(str(props.text))
        )
        return (
            _section_tag("custom_text", props.title, body, design, props),
            True,
        )
    if kind == "letter":
        paragraphs = [str(p) for p in (props.paragraphs or []) if str(p).strip()]
        if not paragraphs:
            return "", False
        basics = snapshot.get("basics") or {}
        meta: list[str] = []
        if props.recipient_name:
            meta.append(f"<div>{esc(props.recipient_name)}</div>")
        if props.recipient_org:
            meta.append(f"<div>{esc(props.recipient_org)}</div>")
        body = ""
        if meta or props.date_label:
            body += (
                "<div class='letter-meta'>"
                + f"<div>{''.join(meta)}</div>"
                + (
                    f"<div class='letter-date'>{esc(props.date_label)}</div>"
                    if props.date_label
                    else ""
                )
                + "</div>"
            )
        if props.subject:
            body += (
                f"<p class='letter-subject'><strong>{esc(props.subject)}</strong></p>"
            )
        body += f"<p class='letter-salutation'>{esc(props.salutation)}</p>"
        body += "".join(
            f"<p class='letter-p'>{inline_md(text)}</p>" for text in paragraphs
        )
        body += f"<p class='letter-closing'>{esc(props.closing)}</p>"
        if props.show_signature and basics.get("name"):
            body += f"<p class='letter-signature'>{esc(basics['name'])}</p>"
        return _section_tag("letter", "", body, design, props), True
    if kind == "spacer":
        return f"<div style='height:{int(props.height_mm)}mm'></div>", True
    return "", False


def _css(design: DesignTokens, page_size: str, shrink: float) -> str:
    width_mm, height_mm = PAGE_MM[page_size]
    margin = _page_margin_mm(design)
    base = round(design.base_size_pt * shrink, 2)
    spacing = round(design.spacing_scale * shrink, 3)
    fonts = FONT_STACKS[design.font_stack]
    if design.font_stack == "mixed":
        body_font = FONT_STACKS["sans"]
        heading_font = FONT_STACKS["serif"]
    else:
        body_font = fonts
        heading_font = fonts
    align = "center" if design.header_style == "centered" else "left"
    heading_transform = {
        "uppercase": "uppercase",
        "title": "capitalize",
        "none": "none",
    }[design.heading_case]
    header_rule = (
        "border-bottom:2px solid var(--accent);padding-bottom:4mm;"
        if design.header_style == "banner"
        else ""
    )
    return f"""
@page {{ size: {width_mm}mm {height_mm}mm; margin: {margin}mm; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
:root {{
  --accent: {design.accent_color}; --text: {design.text_color};
  --muted: {design.muted_color}; --heading: {design.heading_color};
  --background: {design.background_color};
}}
body {{
  font-family: {body_font}; font-size: {base}pt; line-height: {design.line_height};
  color: var(--text); background: var(--background);
  --spacing: {spacing};
}}
h1 {{ font-family: {heading_font}; font-size: {round(base * 1.9, 2)}pt; color: var(--heading); letter-spacing: 0.2px; }}
h2 {{ font-family: {heading_font}; font-size: {round(base * 1.15, 2)}pt; color: var(--heading);
     font-weight: {design.heading_weight}; text-transform: {heading_transform}; letter-spacing: 0.8px;
     margin: calc(1.4em * var(--spacing)) 0 0.4em;
     {"border-bottom:1px solid var(--accent);padding-bottom:2px;" if design.heading_rule == "accent" else ""}
     {"border-bottom: 1px solid var(--muted);padding-bottom: 2px;" if design.heading_rule == "line" else ""}
     }}
.icn {{ width: {design.icon_size_mm}mm; height: {design.icon_size_mm}mm; vertical-align: -0.6mm; margin-right: 1mm; }}
.contact-icons .cpi {{ margin-right: 3mm; white-space: nowrap; }}
.contact-icons .cpi.lnk {{ white-space: normal; word-break: break-all; }}
ul.items.items-timeline {{ padding-left: 5mm; position: relative; }}
ul.items.items-timeline > li {{ position: relative; padding-left: 4mm;
     {"margin-bottom: " + str(design.item_gap_mm) + "mm;" if design.item_gap_mm is not None else "margin-bottom: calc(0.6em * var(--spacing));"} }}
ul.items.items-timeline > li::before {{ content: ''; position: absolute; left: -1.4mm; top: 1.2mm;
     width: 2.2mm; height: 2.2mm; border-radius: 50%; background: var(--accent); }}
ul.items.items-timeline {{ border-left: 0.4mm solid var(--accent); }}
.bar-row {{ display: flex; align-items: center; margin-bottom: 1.6mm; }}
.bar-label {{ width: 30%; min-width: 22mm; }}
.bar {{ flex: 1; height: 1.8mm; border-radius: 1mm;
     background: color-mix(in srgb, var(--accent) 15%, var(--background)); }}
.bar-fill {{ display: block; height: 100%; border-radius: 1mm; background: var(--accent); }}
section.cv-card {{ background: color-mix(in srgb, var(--accent) 6%, var(--background));
     border-radius: {design.corner_radius}mm; padding: 2.5mm 3.5mm; }}
section.cv-card h2 {{ border-bottom: none; }}
header.cv-header {{ text-align: {align}; {header_rule} }}
.cv-header-row {{ display: flex; align-items: center; gap: 4mm;
     {"flex-direction: row-reverse;" if align == "center" else ""} text-align: left; }}
.cv-photo {{ object-fit: cover; flex-shrink: 0; }}
.headline {{ color: var(--muted); font-size: {round(base * 1.1, 2)}pt; margin-top: 1mm; }}
.contact {{ margin-top: 1mm; font-size: {round(base * 0.95, 2)}pt; color: var(--muted); }}
.contact a {{ color: var(--accent); text-decoration: none; }}
.sep {{ color: var(--muted); }}
section {{ {"margin-bottom: " + str(design.section_gap_mm) + "mm;" if design.section_gap_mm is not None else "margin-bottom: calc(0.8em * var(--spacing));"} }}
/* Print fragmentation: keep semantic units whole across page breaks. */
h2 {{ break-after: avoid; }}
ul.items > li, ul.ach, .chips, .bar-row, .cv-header-row, section.cv-card {{ break-inside: avoid; }}
section.cv-outline {{ }}
section.cv-accentbar {{ }}
section.cv-block {{ }}
p.summary {{ text-align: justify; }}
.letter-meta {{ display: flex; justify-content: space-between; gap: 4mm; margin-bottom: calc(1em * var(--spacing)); }}
.letter-date {{ text-align: right; color: var(--muted); }}
.letter-subject {{ font-weight: 600; margin-bottom: calc(0.8em * var(--spacing)); }}
.letter-salutation {{ margin-bottom: calc(0.6em * var(--spacing)); }}
.letter-p {{ text-align: justify; margin-bottom: calc(0.6em * var(--spacing)); }}
.letter-closing {{ margin-top: calc(1.2em * var(--spacing)); }}
.letter-signature {{ font-weight: 600; color: var(--heading); }}
ul.items {{ list-style: none; }}
ul.items > li {{ margin-bottom: calc(0.6em * var(--spacing)); }}
.item-title {{ font-weight: 600; color: var(--heading); }}
.item-org {{ color: var(--accent); }}
.item-period {{ float: right; color: var(--muted); font-size: {round(base * 0.9, 2)}pt; }}
.item-detail {{ margin-top: 0.5mm; }}
ul.ach {{ list-style: disc; margin: 0.5mm 0 0 5mm; color: var(--text); }}
.chips {{ display: flex; flex-wrap: wrap; gap: 1.2mm; width: 100%; }}
.chip {{ background: color-mix(in srgb, var(--accent) 12%, var(--background));
        color: var(--heading); border-radius: {max(1, design.corner_radius)}mm;
        padding: 0 1.6mm; font-size: {round(base * 0.95, 2)}pt; }}
.cv-columns {{ display: table; width: 100%; table-layout: fixed;
     border-spacing: {round(design.spacing_scale * 5, 1)}mm 0; margin: 0 -{round(design.spacing_scale * 5, 1)}mm; }}
.cv-sidebar {{ display: table-cell; vertical-align: top; width: {design.sidebar_width_pct}%; background: {design.sidebar_color};
     color: {design.sidebar_text_color}; border-radius: {design.corner_radius}mm;
     padding: {f"{design.sidebar_padding_mm}mm" if design.sidebar_padding_mm is not None else "4mm 4.5mm"}; }}
.cv-main {{ display: table-cell; vertical-align: top;{" padding: " + str(design.main_padding_mm) + "mm;" if design.main_padding_mm is not None else ""} }}
.cv-sidebar h2 {{ color: inherit;
     border-bottom-color: color-mix(in srgb, currentColor 35%, transparent); }}
.cv-sidebar .item-org, .cv-sidebar .item-period {{ color: inherit; opacity: 0.8; }}
.cv-sidebar .item-title {{ color: inherit; }}
.cv-sidebar .chip {{ background: color-mix(in srgb, currentColor 20%, transparent);
     color: inherit; }}
.cv-sidebar a {{ color: inherit; }}
@media screen {{
  html {{ background: #e2e8f0; }}
  body {{ width: {width_mm}mm; min-height: {height_mm}mm; margin: 0 auto; padding: {margin}mm;
         box-shadow: 0 0 4mm rgba(15, 23, 42, 0.18); }}
}}
""".strip()


def render_cv(
    content: TemplateContent,
    snapshot: dict,
    *,
    page_size: str = CvPageSize.A4.value,
    max_pages: int = 1,
) -> RenderResult:
    """Render a CV to print-ready HTML with layout metrics.

    Applies the template's overflow policy: `shrink` scales typography
    down (max 15%), `truncate` drops lowest-priority items, `warn` renders
    everything and reports overflow via metrics.
    """
    validated = validate_blocks(content.blocks)
    design = content.design
    metrics = RenderMetrics()
    metrics.lines_per_page = _lines_per_page(design, page_size)

    use_sidebar = design.layout == "sidebar"
    sidebar_blocks: list[tuple[str, Any]] = []
    main_blocks: list[tuple[str, Any]] = []
    for index, (kind, props) in enumerate(validated):
        target = (
            sidebar_blocks
            if (use_sidebar and block_area(content.blocks[index]) == "sidebar")
            else main_blocks
        )
        target.append((kind, props))

    def render_column(
        pairs: list[tuple[str, Any]], width_share: float = 1.0
    ) -> tuple[list[str], list[tuple[str, Any, int]]]:
        """(per-block bodies, per-body (kind, props, line cost) entries)."""
        bodies: list[str] = []
        entries: list[tuple[str, Any, int]] = []
        for kind, props in pairs:
            body, had_content = _render_block(kind, props, snapshot, design)
            if not had_content:
                metrics.empty_blocks.append(kind)
                continue
            bodies.append(body)
            entries.append(
                (
                    kind,
                    props,
                    _block_lines(kind, props, snapshot, design, page_size, width_share),
                )
            )
        return bodies, entries

    def _effective_share(raw_share: float, padding_mm: int | None) -> float:
        """Column share after subtracting the area's own padding, so line
        estimates reflect the real text width (plan 70 area tokens)."""
        if padding_mm is None:
            return raw_share
        width_mm, _ = PAGE_MM[page_size]
        usable_w = width_mm - 2 * _page_margin_mm(design)
        return max(0.1, (usable_w * raw_share - 2 * padding_mm) / usable_w)

    sidebar_share = (
        _effective_share(design.sidebar_width_pct / 100, design.sidebar_padding_mm)
        if use_sidebar
        else 0.0
    )
    main_share = _effective_share(1.0, design.main_padding_mm)
    main_bodies, main_entries = render_column(main_blocks, main_share)
    sidebar_bodies, sidebar_entries = (
        render_column(sidebar_blocks, sidebar_share)
        if use_sidebar
        else render_column(sidebar_blocks)
    )

    def _page_estimate() -> int:
        """Page extent: columns flow independently side by side, so a
        two-column layout fills max(main, sidebar) pages, not the sum."""
        lpp = metrics.lines_per_page
        return _pages_for(
            sum(e[2] for e in main_entries),
            sum(e[2] for e in sidebar_entries),
            lpp,
            use_sidebar and bool(sidebar_entries),
        )

    metrics.estimated_lines = sum(e[2] for e in main_entries) + sum(
        e[2] for e in sidebar_entries
    )
    metrics.estimated_pages = _page_estimate()
    metrics.overflow = metrics.estimated_pages > max_pages

    shrink = 1.0
    if metrics.overflow:
        if content.pages.overflow_policy == CvOverflowPolicy.SHRINK:
            shrink = max(0.85, math.sqrt(max_pages / metrics.estimated_pages))
            metrics.lines_per_page = _lines_per_page_per_shrink(
                design, page_size, shrink
            )
            metrics.estimated_pages = _page_estimate()
            metrics.overflow = metrics.estimated_pages > max_pages
        elif content.pages.overflow_policy == CvOverflowPolicy.TRUNCATE:
            budget = max_pages * metrics.lines_per_page
            columns = [(main_entries, main_bodies), (sidebar_entries, sidebar_bodies)]
            per_column = use_sidebar and bool(sidebar_entries)
            metrics.truncated = truncate_column(columns, budget, per_column)
            metrics.estimated_lines = sum(e[2] for e in main_entries) + sum(
                e[2] for e in sidebar_entries
            )
            metrics.estimated_pages = _page_estimate()
            metrics.overflow = metrics.estimated_pages > max_pages

    if use_sidebar and any(sidebar_bodies):
        columns = (
            "<aside class='cv-sidebar'>" + "".join(sidebar_bodies) + "</aside>"
            "<main class='cv-main'>" + "".join(main_bodies) + "</main>"
            if design.sidebar_side == "left"
            else "<main class='cv-main'>" + "".join(main_bodies) + "</main>"
            "<aside class='cv-sidebar'>" + "".join(sidebar_bodies) + "</aside>"
        )
        document = f"<div class='cv-columns'>{columns}</div>"
    else:
        document = "".join(main_bodies + sidebar_bodies)
    html_out = (
        '<!DOCTYPE html>\n<html lang="en">\n<head><meta charset="utf-8">'
        f"<title>CV</title><style>{_css(design, page_size, shrink)}</style></head>"
        f"<body>\n{document}\n</body>\n</html>\n"
    )
    return RenderResult(html=html_out, metrics=metrics)


def _lines_per_page_per_shrink(
    design: DesignTokens, page_size: str, shrink: float
) -> int:
    shrunken = design.model_copy(
        update={"base_size_pt": round(design.base_size_pt * shrink, 2)}
    )
    return _lines_per_page(shrunken, page_size)


def truncate_column(
    columns: list[tuple[list[tuple[str, Any, int]], list[str]]],
    budget: int,
    per_column: bool,
) -> int:
    """Drop whole lowest-priority blocks (never the header) in place.

    `columns` is a list of (entries, bodies) lists in combined render
    order (main last scanned → sidebar blocks go first, matching the
    previous combined-order behavior). With `per_column` (two real
    columns) each column truncates against its own `budget`; otherwise
    a single shared budget applies to the stacked result. Never leaves
    fewer than one live block anywhere, and the `header` never drops.
    """
    dropped = 0
    two_columns = per_column and len(columns) > 1

    def col_lines(index: int) -> int:
        entries, _bodies = columns[index]
        return sum(entry[2] for entry in entries)

    def live_blocks() -> int:
        return sum(
            len([entry for entry in entries if entry[2] > 0])
            for entries, _bodies in columns
        )

    while True:
        targets = (
            [i for i in range(len(columns)) if col_lines(i) > budget]
            if two_columns
            else [len(columns) - 1]
            if col_lines(len(columns) - 1) > budget
            else []
        )
        if not two_columns and sum(col_lines(i) for i in range(len(columns))) > budget:
            targets = list(range(len(columns) - 1, -1, -1))
        elif not targets:
            break
        victim: tuple[int, int] | None = None
        for column in targets:
            entries, _bodies = columns[column]
            for index in range(len(entries) - 1, -1, -1):
                if entries[index][0] == "header":
                    continue
                victim = (column, index)
                break
            if victim is not None:
                break
        if victim is None or live_blocks() <= 1:
            break
        column, index = victim
        entries, bodies = columns[column]
        entries[index] = (entries[index][0], entries[index][1], 0)
        bodies[index] = ""
        dropped += 1
    return dropped
