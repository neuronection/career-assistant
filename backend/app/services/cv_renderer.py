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
from app.services.cv_blocks import validate_blocks

FONT_STACKS = {
    "sans": "-apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    "serif": "Georgia, 'Times New Roman', serif",
    "mixed": None,  # headings serif, body sans
    "geometric": "'Century Gothic', 'Avenir Next', 'Futura', Verdana, sans-serif",
}

DATE_FORMATS = {"mon_yyyy", "iso", "eu", "year"}

SOURCE_DEFAULT_TITLES = {
    "experience": "Experience",
    "education": "Education",
    "certifications": "Certifications",
    "projects": "Projects",
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


def _block_lines(kind: str, props: Any, snapshot: dict) -> int:
    """Estimated line cost of one block from the snapshot."""
    if kind == "header":
        return 4
    if kind == "summary":
        text = str(snapshot.get("summary") or "")
        return math.ceil(len(text) / 85) + 1 if text else 0
    if kind == "items":
        items = snapshot.get(props.source_key) or []
        per_item = (
            2 + (1 if props.show_skills else 0) + (1 if props.show_achievements else 0)
        )
        return min(len(items), props.max_items) * per_item + 1
    if kind == "skills":
        count = len(snapshot.get("skills") or [])
        return math.ceil(min(count, props.max_items) / 6) + 1
    if kind == "languages":
        return (1 if snapshot.get("languages") else 0) + 1
    if kind == "achievements":
        return min(len(snapshot.get("achievements") or []), 10) + 1
    if kind == "interests":
        return (
            math.ceil(min(len(snapshot.get("interests") or []), props.max_items) / 8)
            + 1
        )
    if kind == "custom_text":
        return math.ceil(len(str(props.text)) / 85) + 1
    if kind == "letter":
        paragraphs = [str(p) for p in (props.paragraphs or []) if str(p).strip()]
        lines = sum(math.ceil(len(text) / 85) for text in paragraphs) + 3
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

    def piece(name: str, text: str, url: str | None = None) -> str:
        mark = icon(name) if show_icons else ""
        body = esc(text)
        value = f'<a href="{esc(url)}">{body}</a>' if url else body
        return f"<span class='cpi'>{mark}{value}</span>"

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
            label = link.get("label") or link.get("kind") or link.get("url")
            if label and link.get("url"):
                parts.append(
                    piece(
                        LINK_KIND_ICONS.get(link.get("kind"), "link"),
                        label,
                        _safe_href(link.get("url")),
                    )
                )
    if show_icons:
        return "<span class='contact-icons'>" + " ".join(parts) + "</span>"
    return " <span class='sep'>·</span> ".join(parts)


def _render_items(items: list, props: Any) -> str:
    rows = []
    for item in items[: props.max_items]:
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
        if not items:
            return "", False
        title = props.title or SOURCE_DEFAULT_TITLES.get(
            props.source_key, props.source_key
        )
        return (
            _section_tag("items", title, _render_items(items, props), design, props),
            True,
        )
    if kind == "skills":
        skills = snapshot.get("skills") or []
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
        chips = "".join(
            f"<span class='chip'>{esc(lang.get('label') or lang.get('code') or lang)} — {esc(lang.get('level', ''))}</span>"
            if isinstance(lang, dict)
            else f"<span class='chip'>{esc(lang)}</span>"
            for lang in languages
        )
        return (
            _section_tag(
                "languages",
                props.title,
                f"<div class='chips'>{chips}</div>",
                design,
                props,
            ),
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
.chips {{ display: flex; flex-wrap: wrap; gap: 1.2mm; }}
.chip {{ background: color-mix(in srgb, var(--accent) 12%, var(--background));
        color: var(--heading); border-radius: {max(1, design.corner_radius)}mm;
        padding: 0 1.6mm; font-size: {round(base * 0.95, 2)}pt; }}
.cv-columns {{ display: flex; gap: {round(design.spacing_scale * 5, 1)}mm;
     align-items: stretch; }}
.cv-sidebar {{ width: {design.sidebar_width_pct}%; background: {design.sidebar_color};
     color: {design.sidebar_text_color}; border-radius: {design.corner_radius}mm;
     padding: 4mm 4.5mm; }}
.cv-main {{ flex: 1; min-width: 0; }}
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
            if (use_sidebar and content.blocks[index].get("column") == "sidebar")
            else main_blocks
        )
        target.append((kind, props))

    def render_column(pairs: list[tuple[str, Any]]) -> list[str]:
        bodies: list[str] = []
        for kind, props in pairs:
            body, had_content = _render_block(kind, props, snapshot, design)
            if not had_content:
                metrics.empty_blocks.append(kind)
                continue
            bodies.append(body)
            metrics.estimated_lines += _block_lines(kind, props, snapshot)
        return bodies

    main_bodies = render_column(main_blocks)
    sidebar_bodies = render_column(sidebar_blocks)

    metrics.estimated_pages = max(
        1, math.ceil(metrics.estimated_lines / metrics.lines_per_page)
    )
    metrics.overflow = metrics.estimated_pages > max_pages

    shrink = 1.0
    if metrics.overflow:
        if content.pages.overflow_policy == CvOverflowPolicy.SHRINK:
            shrink = max(0.85, math.sqrt(max_pages / metrics.estimated_pages))
            metrics.estimated_pages = max(
                1,
                math.ceil(
                    metrics.estimated_lines
                    / _lines_per_page_per_shrink(design, page_size, shrink)
                ),
            )
            metrics.overflow = metrics.estimated_pages > max_pages
        elif content.pages.overflow_policy == CvOverflowPolicy.TRUNCATE:
            all_bodies = main_bodies + sidebar_bodies
            all_pairs = main_blocks + sidebar_blocks
            budget = max_pages * metrics.lines_per_page
            truncate_blocks(all_bodies, all_pairs, snapshot, budget, metrics)
            main_bodies = all_bodies[: len(main_blocks)]
            sidebar_bodies = all_bodies[len(main_blocks) :]

    if use_sidebar and sidebar_bodies:
        sidebar_html = "".join(sidebar_bodies)
        main_html = "".join(main_bodies)
        columns = (
            f"<aside class='cv-sidebar'>{sidebar_html}</aside>"
            f"<main class='cv-main'>{main_html}</main>"
            if design.sidebar_side == "left"
            else f"<main class='cv-main'>{main_html}</main>"
            f"<aside class='cv-sidebar'>{sidebar_html}</aside>"
        )
        document = f"<div class='cv-columns'>{columns}</div>"
    else:
        document = "\n".join(main_bodies + sidebar_bodies)
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


def truncate_blocks(
    bodies: list[str],
    validated: list[tuple[str, Any]],
    snapshot: dict,
    budget: int,
    metrics: RenderMetrics,
) -> None:
    """Drop whole lowest-priority blocks until the estimate fits (never the header)."""
    order = list(range(len(bodies)))
    while metrics.estimated_lines > budget and len(order) > 1:
        victim = order[-1]
        kind, props = validated[victim]
        if kind == "header":
            break
        metrics.estimated_lines -= _block_lines(kind, props, snapshot)
        order.pop()
    keep = set(order)
    for index in range(len(bodies)):
        if index not in keep:
            bodies[index] = ""
    metrics.truncated = len(validated) - len(order)
