# Templates and design

Career Assistant renders every CV through **one deterministic engine**. A
template is a validated version of block definitions plus design tokens —
never a one-off document — so a CV is reproducible and its exports match the
preview exactly.

## The template bank

Templates live in a versioned bank. The bank ships a range of layouts
(classic, sidebar, and magazine-style photo + skill-bar layouts such as
`coral-banner` and `charcoal-amber`) and you can customize any of them into
your own copy.

- **Gallery** previews templates **with your own data** (not lorem ipsum), so
  you see the real result before choosing.
- **Two-template compare** shows a side-by-side view.
- Every template is a validated version, and import/export is file-first and
  hash-verified.

## The design-token editor

Open a CV's **Design** tab for "How my CV looks". It is one place — template
card, style, photo and printed review — over a pinned Apply/Reset footer.
Tokens include:

| Group | Tokens |
|---|---|
| **Colors** | Accent and palette |
| **Typography** | Font size and embedded fonts (`embedded-sans` / `embedded-serif` ship as vendored, OFL-licensed WOFF2 subsets) |
| **Spacing** | Per-area paddings (main and sidebar), page margins |
| **Layout** | Two-column newspaper flow (`main_columns` / `sidebar_columns`), sidebar widths |
| **Section headings** | Optional icons (`show_heading_icons`), per-block icons |
| **Photo** | Photo shapes (including an `arch` shape) |
| **Skill bars** | Bars, and `grouped` skill categories with subheadings |
| **Headers/footers** | Page-2+ running headers and footers |
| **Name style** | Including `accent_surname` |
| **Elevation** | Per-section containers and an elevation token for expressive looks |

Ranges in the editor match the backend's validation bounds, and config changes
autosave and remain undoable.

## Printed-page visual review

Because the printed PDF is the page-count truth, the Design tab includes a
**printed-page visual review**: you see the actual rendered pages, not an
approximation. Live page-break rules in the canvas keep headings and units
from splitting badly (`break-inside: avoid`, `break-after: avoid`).

## Blocks

The CV is composed of **registered block kinds** — a kind binds a props schema
and renderer behaviour. This is why templates can offer a coherent set of
sections and why exports (PDF, DOCX, Markdown, ATS) stay consistent with the
preview. See the [CV engine](../dev/cv-engine.md) for the developer view.

## Related

- [CV Studio overview](cv-studio.md)
- [Variant library](cv-variants.md) — change the words, not the design
- [Feature catalog](features.md#cv-studio) — the full design surface
