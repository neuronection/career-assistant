# CV engine

CV Studio is the most mature surface in the app, and it has the most moving
parts. This page is the developer map: how a CV is composed, rendered,
resolved, generated and measured. The user-facing view is
[user/cv-studio.md](../user/cv-studio.md).

## Block kinds

`app/services/cv_blocks.py` — `register_block_kind` binds a kind to a props
schema and renderer behaviour. Blocks carry an **area** mark (`main` /
`sidebar`; legacy `column` accepted) that sidebar layouts honor when grouping
columns. A `header` block may live in either column and the sidebar column
inherits its text color for contrast. Cover letters reuse the pipeline through
the `letter` kind.

Design tokens include per-area paddings (`main_padding_mm` /
`sidebar_padding_mm`), `header_style: "band"`, `grouped` skill categories,
`show_heading_icons` + per-block `icon`, `photo_shape: "arch"`,
`name_style: "accent_surname"`, `main_columns` / `sidebar_columns` newspaper
flow, and `font_stack: "embedded-sans" / "embedded-serif"` (vendored OFL WOFF2
subsets inlined by `app/services/cv_fonts.py`; missing files fall back to the
system stack — capability-detected). The template bank seeds live in
`app/seeds/cv_templates.py`.

## Context and sources

`app/services/cv_context_service.py` — `register_context_source` binds a
profile entity to a typed resolver. Selection resolves **deterministically**
into the renderer snapshot with per-item traceability; ineligible profile data
is never registered, so it cannot reach a CV. The experience table splits into
three sources (plan 70): `experience` (paid work only), `projects`
(kind=project) and `volunteer` (kind=volunteer) — preserving the generate
machinery's `section kind == source_key` invariant.

## Variants

Synthesized variants live in the user-level `cv_synth_items` library
(`app/services/cv_synth_service.py`), not in the profile. Each variant cites
typed source refs + source content hashes (staleness/orphan detection) and
applies through the per-CV `context.synth_mode` overlay **before** editor
overrides. Precedence is always **override > synth > source**, and every
application is traced via `synth_applied` in the version's
`context_resolution` and the live resolution payloads.

- **Plan 110 (one variant per item)** collapsed the two-layer pin slots into a
  single pin. `swap_variant_payload` applies by **field presence**
  (description → text layer; `achievements` → bullets; both → full entry)
  regardless of the row's `scope` (now pure provenance). `_supersede_slot` is
  whole-row (one-variant window per refset/variant_key/posting) and remaps any
  star pointing at an archived sibling onto the new owner.
- Pins are written **surgically** via `PUT /cv/{id}/context/pin`
  (`{source_key, item_id, synth_id|null}`) — read-modify-write of the one slot,
  promoting a pinned draft to active in the same commit, so a stale client map
  cannot erase another slot's star.
- A pinned ref is **exclusive** in the highlights snapshot: when the star
  cannot apply, the item renders profile text and no other variant jumps in.

## The builder service and ops

`app/services/cv_builder_service.py` owns the builder document, resolution and
the `BuilderOp` vocabulary. Both the UI (`POST /cv/{id}/ops`) and the copilot
converge on `cv_builder_chat.apply_operation` — one audited code path. Bank
templates auto-customize to a private copy on first edit.

## Generation and the polish loop

`app/services/cv_generate_service.py` runs the `cv_generate` background job,
which drives the `cv_draft` LangGraph (`app/ai/graphs/cv_draft.py`):
plan → enrich (fetch a few of your own linked pages) → synthesize → assemble.
After the assemble node, the **polish loop** (plan 64) runs the
`cv_build_review` vision task (`app/ai/agents/cv_build_reviewer.py`), which
critiques the rendered pages + lint + a deterministic coverage matrix
(`build_coverage_matrix`), and a bounded fix/applicant node applies its
`BuilderOp` suggestions through the same audited path. Design edits
materialize as new template versions; variants ground through the `cv_synth`
task. The polish trace lives on the final `ai_apply` version payload and the
job result — never in `working_content`.

Run linkage: `GET /cv/{id}/runs` assembles per-CV runs from job rows and their
run-linked `ai_generations` rows; the UI renders them with the family
`flow-trace` module.

## Pagination: estimated, then measured

`app/services/cv_renderer.py` computes `estimated_pages` from per-column wrap
math and honors them per column (two-column layouts fill
`max(main, sidebar)` pages). **The printed PDF is the truth:**
`cv_pdf_service.measure_pages` prints the document once through a persistent
headless-Chromium browser, counts the PDF's own page tree via pypdfium2 (never
clamped) and rasterizes the exact printed pages for the vision critique. Lint
prefers that live print over the last export's stamp (`page_count_source` says
which), and PDF exports stamp it onto the compiled version
(`content.render.pages_actual`). Break-quality is CSS-only (`break-inside:
avoid` on semantic units, `break-after: avoid` on headings).

## Language and icon registries

- `app/services/cv_languages.py` — ISO code → human name (with title-cased
  fallback), profile level → CEFR band, and the proficiency-exam vocabulary
  that lets the `languages` block claim the latest matching certification.
- `app/services/cv_icons.py` — `SECTION_KIND_ICONS` glyph vocabulary.

## Exports

`app/services/cv_export_service.py` branches on block kind via `_visible_blocks`
for Markdown/ATS/DOCX exports, keeping every format consistent with the
preview. PDF goes through the print engine.

## Related

- [AI layer](ai-layer.md) — the gateway the CV flows use
- [Data model](data-model.md) — `cv_documents`, `cv_versions`, `cv_templates`, `cv_synth_items`
- [UI conventions](ui-conventions.md) — the CV workspace patterns
- [User: CV Studio](../user/cv-studio.md)
