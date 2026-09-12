# Changelog

All notable changes to **Career Assistant** are documented here.

## [Unreleased]

### Fixed
- **CI checks are honest again on `main`**: a fresh SQLite database
  migrates cleanly through the whole chain, the AI type-gate (mypy)
  is green across `app/ai`, and the E2E smoke can run against both a
  repo checkout (venv) and a CI environment (system python). Desktop
  checkpoints live in their own `checkpoints.db` so live AI runs no
  longer deadlock the app database under WAL.

## [v0.8.3] - 2026-09-12

### Fixed
- **Linux packages run on older distros**: the bundled
  Linux libraries were built on glibc 2.38+ (Ubuntu 24.04) and refused to
  load on Ubuntu 22.04 / Debian 12 (and older) with
  `libm.so.6: version 'GLIBC_2.38' not found`. Linux packaging and CI
  packaging now build on Ubuntu 22.04, like study-assistant.
- **GPU-less machines get WebKit in software rendering**: if EGL can't
  initialize on the default display (VMs, no-GPU machines), the desktop
  shell falls back to software rendering, then to browser mode — instead
  of showing a dead window. Forced GPU via `CA_WEBKIT_GPU=1`.
- **pygobject pinned to the girepository-1.0 era** (`<3.51`): 3.58 only
  builds against girepository-2.0, absent from the glibc-2.35-compat
  runner.

## [v0.8.1] - 2026-09-12

### Fixed
- **Desktop installs migrate cleanly again (v0.8.1)**: two database
- **Desktop installs migrate cleanly again (v0.8.1)**: two database
  migrations assumed Postgres dialect and crashed a fresh desktop profile
  (SQLite) mid-setup — the CV-document cascade update and the optional
  project start date now go through the SQLite-safe batch mode, plus a
  regression test that migrates a fresh SQLite file all the way to head.

## [v0.8.0] - 2026-09-12

### Changed
- **The floating chat bubble is now opt-in (plan 75)**: the always-on
  launcher button is gone. The docked chat panel is the default chat
  surface; the compact popup bubble appears — and stays — only after
  you pick the popup view (your choice is remembered). The docked panel
  also gained a proper close button that hands off to the popup.
- **No more login wall (transitory)**: the app now runs in single-user mode —
  it never asks to register or sign in; a single default user (admin) is
  created automatically on first use and used for everything. Desktop mode
  works out of the box on a fresh database. Self-hosters who want the classic
  multi-user flow can set `SINGLE_USER_MODE=false` in `.env` to restore the
  JWT login; presented tokens stay valid in both modes.

### Added
- **Test watchdog**: the backend test suite now runs under `pytest-timeout`
  (120s per test) so a hung test fails with a stack dump instead of freezing
  the session.
- **Projects don't need dates anymore**: project entries in your experience
  (and projects parsed from an imported CV) can now have no start date —
  only jobs, internships, freelance and volunteering still require one.
  Undated projects sort last within their section. The CV import agent's
  guidance updated so it leaves dates empty instead of guessing.
- **Write synthesized variants yourself (plan 72)**: variants are no
  longer AI-only — write them from the variant library ("Add variant")
  or directly from the CV Studio context panel (the "+" next to the
  Improve-with-AI wand) with a description, bullet points, a variant
  key, a language and an optional posting scope. Creating is immediate:
  the variant goes live and applies to matching CVs.
- **The context panel is now a synth tree**: variants appear under
  every source they touch (cross-listed, with referenced-item chips,
  stale/"source gone" badges) and their status toggles inline — with a
  clear hint that activating replaces the active variant for the same
  items.
- **Custom highlights section**: the add-section picker gained a
  "Custom highlights" card that renders your synthesized variants as
  their own section — limited to chosen variants, with the items each
  entry is based on printed as small chips (toggleable). Exports
  (markdown, ATS text, DOCX) and the lint report honor it.
- **Reorder items inside a section** (plan 72): each experience/…
  section's config gained a "Reorder items" disclosure with drag
  handles and up/down buttons — your order decides what survives the
  "max items" truncation and is remembered per CV.
- **Template customization moves into CV Studio (plan 71)**: the CV builder
  gained a **Template tab** with the full design-token editor — typography
  (line height, spacing scale), colors, headings, section/page spacing,
  sidebar layout and paddings — applying through the same audited path the
  AI copilot uses (bank templates are customized to your own copy
  automatically). Page size is now editable from the builder.
- **Per-section container styling** (background, border, radius, padding)
  is configurable in the builder's section editor, and block options are
  consistent between the builder and the template editor (experience kind
  filters, proficiency-certificate hiding, CEFR bands, header contact
  links/location).
- **Visual review surfaces**: the copilot's structured page critique now
  renders in the AI tab with one-click "apply suggested fixes", and the
  Template tab accepts printed-page photos (PNG/JPEG) for a vision review
  of your printed CV — degrading gracefully to lint-only when no vision
  model is configured.
- **Assessment templates can be AI-drafted** ("Draft with AI" in the test
  library — review-first, saved as a private template), and job
  enrichment proposals are reviewable in Settings → Taxonomy → Enrichment
  (apply/discard per proposal).
- **Generate-with-AI dialog now matches what it shows**: it stays compact
  while you fill the preferences (and while the job runs before the first
  preview pages commit), then widens the moment the live draft preview
  renders. On small screens the dialog always fills the full screen.
- **Generated CVs split experience by category (plan 70)**: one-shot
  generation now emits separate **Work Experience** (jobs, internships,
  freelance), **Projects** and **Volunteering** sections instead of
  merging everything into one Experience list. Profile experience items
  resolve as three distinct context sources, so the generate modal offers
  the three toggles independently and the AI plans them as separate
  sections.
- **Per-area template styling (plan 70)**: templates gained
  `main_padding_mm` / `sidebar_padding_mm` design tokens. Sidebar-layout
  bank templates now use a zero page margin with per-area paddings so the
  colored column runs full-bleed and spacing is owned per area; the
  template editor exposes both controls for sidebar layouts. Items
  sections also gained an optional kind filter (Jobs / Internships /
  Freelance) in the builder's section editor.
- **Synth-aware CV generation (plan 69.1)**: "Generate with AI" now reuses
  your synthesized variant library — with the CV context set to prefer
  synthesized items, matching active variants (posting-scoped first) replace
  the profile text **before** the AI drafts, and the run result records which
  variants were applied (`synth_applied` trace on the run and the compiled
  version). Off mode is unchanged (byte-compat).
- **Synth-aware CV generation (plan 69.2)**: when the AI planner judges a
  posting demands emphasis a profile item cannot show from its text, it can
  propose gap variants (≤3 per run) — they are grounded as **draft** rows in
  your variant library (cited to the source item, run-audited) and the fresh
  CV is drafted on their tailored text; pending variants are listed in the
  run result (`synth_proposed`) for review in the library.
- **Synth-aware CV generation UI (plan 69.3/69.4)**: the "Generate with AI"
  modal grew a "Prefer synthesized items" option with a live pre-run hint
  ("N of your synthesized variants will replace their profile text in this
  CV"), and after a generation that reused and/or created variants a review
  screen shows exactly what the library contributed before the builder
  opens (review-variants deep link included). Read-only
  `POST /cv/synth/preview` backs the hint.
- **Fixed: editing a self-rated skill's level no longer deletes every
  other self-rated skill.** The slider saved a single-item payload and
  the skills PUT replaces the caller's self-report rows — each drag
  silently dropped the rest; saving now always spans the full
  self-report set (regression-tested).
- **Skills can be deleted for good** (`DELETE /me/skills/{id}`,
  migration 0031's `user_skills.hidden` tombstone): every source now
  shows a delete action on /profile#skills (self-report rows already
  had one). A deleted skill is hidden from every surface, is excluded
  from scoring, and derivation never re-creates it — re-adding it via
  the search makes a fresh editable rating.
- **Skill level ownership (plan 68)**: experience skills now accept an
  optional claimed level (1–10) in the editor, and derivation treats
  claims as calibration — a claim within ±2 of the months-curve
  confirms it (confidence +0.2), a larger gap records an explicit
  conflict with the claimed level and never silently overrides. On the
  Skills page, imported (experience/document) rows gained a
  derivation tooltip ("≈ level X from N months of evidence") and an
  **edit** action that converts the imported estimate back into your
  own editable rating, plus a **disable** opt-out (`derive_enabled`
  toggle, migration 0030) that freezes the estimate — derivation
  neither updates nor re-creates the row until re-enabled. The skills
  list is now flat (all sources together in level order, badge +
  per-row actions only), and the add-skill combobox is a compact
  right-aligned popover under the list. Role labels now show their
  evidence impact (primary 1.0× / secondary 0.6× / exposure 0.3×).
  The experience page's "Apply to my skills" button is gone:
  estimates apply automatically after every entry change and the
  panel is now a summary-only readout. **Disabled skill estimates are
  excluded everywhere downstream** — CV Studio context, the fit
  engine, fit/posting coverage, gaps, and all LLM scoring surfaces
  (cover-letter brief, CV suggestions) treat an opted-out skill as
  unclaimed;   assessment/micro-run writes also never touch a frozen
  row (flagged as a conflict), and re-saving a disabled row on the
  Skills page re-enables it. The ±2 review-first guard now protects
  only self-owned rows: machine-sourced estimates (document, CV
  parse, experience derivation) always follow the fresh curve, so
  stale rows no longer diverge from the estimate panel.
- **Generate-progress preview takes the full column height**: the
  modal's right pane is a fixed full-height scroll surface for the A4
  draft (was a shrunken aspect-ratio box), and no placeholder box
  renders before the first pages commit — the preview appears only
  once the draft is ready.
- **Per-item skills selection end-to-end + per-round include/omit
  assessment**: the generation plan may now pick a relevance subset of
  skills (not always "all profile skills") — the chosen ids ride the
  skills block (`props.selected`) and the renderer lists only those
  (with the page-cost estimate honoring the subset). The polish loop's
  coverage issue now suggests a concrete `set_context` op — the current
  selection + the uncovered items — instead of a generic `max_items`
  nudge, so each round can actually include/omit items.
- **Instant "Generate" submit** — the AI template pick moved into the
  background run (contract: `CvGenerateRequest.template_pick`): the
  modal no longer awaits the suggestion call on the request path
  (~40 s + with a cold provider), so pressing Generate shows the
  progress view immediately; the pick itself still runs audited inside
  the job and only reorders the studio-default candidates, a pick
  failure never fails the run. The running-state popup is a
  near-fullscreen two-pane workspace — status/telemetry/trace left,
  live preview right.
- **Paste-a-posting targeting in "Generate with AI"**: users can copy
  the whole job ad from any careers page into a new **"Or paste a job
  posting"** field (≤5000 chars, auto-grow) — the first non-empty line
  names the role and the generated CV ("CV — {role}"), the full text
  rides into the plan/write prompts as the run's target. A saved
  target posting still takes precedence (pasted text then warns and is
  ignored). The emphasis-notes limit rises to 5000 to match. Contract
  change: `CvGenerateRequest.posting_text`, `notes` now ≤5000 —
  openapi contract regenerated.
- **CV Studio build-progress consolidation** (plan 67): the builder
  page is now the build dashboard — a CV-scoped **Copilot activity
  card** mirrors every live chat turn's phases, tool cards and outcome
  (even with the chat dock closed, driven by the stream's node/tool
  events only — text stays in the chat), falling back to the persisted
  turn trace after the turn lands; the **Run progress card** renders a
  running generate/polish job in the builder via the runs mirror poll
  (status chip, telemetry strip, cancel, resume-on-failure) and flips
  to the final trace + Runs & metrics entry on completion — a live
  turn takes the full card and the running job collapses to its
  telemetry strip (one view-model: all faces render through the shared
  `cvBuildTrace` mappers onto the library `FlowTrace` card, and the
  create-flow's progress timeline is retired onto the same renderer).
  Cross-surface links: a builder turn that produced a version gains an
  "Open in CV Studio" chip in the chat transcript, and the run card
  footer gains "Ask the assistant" to open the docked chat on the CV
  session. "Generate with AI" now lands the completed draft in the
  builder with the copilot docked on the new CV's pinned session.
- **Generate-flow emphasis textarea auto-grows** (plan 67 follow-up):
  "What should this CV emphasize?" now expands with the content (up to
  360 px, then the modal scrolls) instead of a fixed 3-row box with an
  internal scrollbar — long emphasize lists / posting excerpts get the
  space they need; still capped at the 2000-character backend limit.
- **Polish notes moved off the builder canvas** (plan 67 follow-up):
  the AI polish review log no longer sits permanently above the editor
  eating vertical space — a toolbar **Notes** button (next to
  Versions / AI runs, shown only when polish notes exist) opens the
  full review log in a popup, leaving the viewport to the editor.
- **Runs & metrics surface UI** (plan 65.4/65.5, with the family library
  release): the new `@neuronection/assistant-ui/flow-trace` module
  (`FlowTraceCard` run-ledger card + `FlowTelemetryStrip` live counters,
  verified in career and study) powers the two career surfaces — the
  generate progress card shows a live `calls · tokens in/out · edits`
  telemetry strip under the polish timeline (mock-provider runs badge
  themselves *Simulated* — fake spend never masquerades as real), and
  CV Studio's builder toolbar gains an **AI runs** entry: a "Runs &
  metrics" popup that lists the generation run plus every polish
  re-run, newest first, each expandable into the stage timeline, the
  per-call LLM ledger (task, stage, provider+model, tokens, latency,
  prompt version), the applied/rejected ops list, coverage drops and
  the run outcome (with resume chains and the compiled `final v{n}`
  per run; `final_version` added to the runs endpoint).
- **`GET /cv/{cv_id}/runs` — runs & metrics per CV** (plan 65.3): the
  generation run plus every polish re-run, newest first, each with the
  polish trace (stage timeline, per-iteration ops ledger, coverage,
  verdicts, outcome incl. resumed links), the run's LLM-call ledger
  from `ai_generations` (task, stage, provider+model, tokens in/out,
  latency, prompt version; `mock` rows badge themselves) and per-run
  per-task aggregates. Owner-scoped (404 for foreign CVs), empty for
  CVs without runs, and it finds still-RUNNING jobs through the CV's
  mid-run run id. OpenAPI regenerated (257 → 258 paths).
- **Mid-run LLM-call ledger on the live preview** (plan 65.2): the polished
  run's mid-run mirror now carries `llm_calls` — one entry per audited
  gateway call (task, stage, provider+model, tokens in/out, latency,
  status), read from the run-linked `ai_generations` rows — so the
  progress card's telemetry strip can show model calls and tokens while
  the loop is still working, and the finalized trace keeps the same
  ledger. The gateway also grows an opt-in `with_audit_ref` return
  (value + the audit row it just wrote, no second SELECT), used by the
  polish review node to pin the exact audit id of each iteration.
- **Run telemetry groundwork** (plan 65.1): the `ai_generations` audit
  ledger gains optional `run_id`/`run_stage` columns — multi-step flows
  (CV generation, the polish loop) now opt each call into the audit row
  via a `RunRef` on the gateway, so a run's LLM-call ledger (task, model,
  tokens, latency, stage) can be consulted per run. Nullability keeps
  every single-call/sync audit row byte-identical to today; no schema
  behavior change otherwise.
- **CV-builder copilot turn trace** (plan 66): builder turns now keep the
  same execution trace the chatbot persists — every turn streams a
  "Reading the builder state" tool card plus per-operation cards with
  honest durations (`duration_ms` fixed on the wire), and after the turn
  the tool cards + phase/tool timeline stay on the message with
  expandable arguments/response detail (no more vanishing cards on
  reload). Failed turns still record what ran.
- **Live draft preview + resume while AI CVs generate/polish** (plan
  64.5): `GET /cv/generate/{job_id}/preview` renders the currently
  committed draft state (deterministic render, refreshed by polling —
  progress-card iframe or standalone); `POST /cv/{cv_id}/polish`
  re-runs the polish loop over any generated CV (*Resume polish* after
  a failed/cap-stopped run or a manual "polish again"), chaining the
  trace via `resumed_from`. Job results now carry the polish trace.
  Frontend (64.6): the progress card live-previews the transforming
  draft in an iframe with per-pass counts, a failed run offers
  *Resume polish* / open-the-builder actions, and the builder shows an
  AI review-log card (the user's prompt, per-pass findings grouped
  Errors/Warnings/Info, applied and rejected edits, coverage drops and
  the outcome).
- **Agentic CV polish loop** (plan 64 first slices): one-shot generation
  now reviews its own output — a `cv_build_review` vision task looks at
  the rendered pages, the deterministic coverage audit compares every
  selected context item against what landed (missing-but-usable items
  become findings), and a bounded fix loop (max 3 iterations, max 6 ops
  each) applies the reviewer's suggested builder ops through the exact
  audited path the copilot uses. Design/theme edits never mutate a
  template in place: they land as new template versions via the
  template version control; weak items get grounded CV_SYNTH variants
  that the next review keeps (persisted to the variant library as
  drafts) or reverts. The final `ai_apply` version carries a
  full polish trace (the user's prompt, per-iteration issues, applied
  and rejected ops, lint facts, coverage matrix, template chain,
  audit ids), and the loop stops deterministically (`completed` or
  an explicit non-failure `cap` outcome).
- **Ask AI to choose a template** (`CV_TEMPLATE_PICK` task + `POST
  /cv/templates/suggest`): the New CV form gains an "Ask AI to choose"
  action — template candidates are pre-scored deterministically
  (language match, sidebar layout, ATS-safety) and the AI may only
  reorder them with one-line reasons; Suggestion picks apply with one
  tap, and an unconfigured provider disables the button with a hint
  instead of erroring the form.
- **New CV form embeds template selection** (plan 63.5): title +
  template together in the create form — chosen template shows a live
  preview with "use the studio default" fallback, the gallery remains
  the shared browse/customize/AI-generate surface.
- **Generate-with-AI gets a first-class template choice with a smart
  default** (plan 63.5): Template is no longer an Advanced option —
  the default "Best for me (AI picks)" resolves via
  `POST /cv/templates/suggest` at submit time (so AI-generated CVs
  vary across templates instead of stacking on the first one), falls
  back to the studio default when the provider is unconfigured, and
  the explicit choices ("Studio default", any template) are always
  available.

### Changed
- **One-shot CV generation is now layout-aware** (plan 63.3): the
  `cv_draft` flow adopts the selected template's block skeleton, so
  generated sections land in the template's declared `main`/`sidebar`
  areas exactly like manually created CVs — previously every generated
  section defaulted to the main column, leaving sidebar templates with
  an empty panel.

### Fixed
- **CV template picker** (Cv Studio "Use templates"): preview frames no
  longer scroll or capture the wheel (each card used to be its own
  scroll container); only the CV preview area of the card is now the
  "use" click target with its hover overlay across it, so the
  redundant bottom Use button is gone (title/description/Customize
  stay non-click-through).
- **Dev backend auto-reload no longer hangs.** uvicorn waited for
  keep-alive/SSE connections to close indefinitely on reload; the dev
  Procfile now caps shutdown at 5s
  (`--timeout-graceful-shutdown`).
- **PDF export chips match the preview.** In the exported PDF, skill
  chips inside sidebar items collapsed to one-per-row (max-content
  flex sizing in headless Chromium's initial layout). `.chips` now
  sets `width: 100%`, so the export wraps chips exactly like the CV
  Studio preview.
- **Deleting a CV document no longer fails.** `skill_evidence`
  referenced documents with an `ON DELETE SET NULL` foreign key while a
  CHECK requires exactly one source set, so deleting an uploaded CV
  (#/profile/import path) 500'd. The FK cascades now (migration `0028`),
  matching the other two evidence sources.

### Changed
- **Synthesized CV items: frontend (plan 62.5).** The variant library at
  `/cv/synth` (linked from CV Studio): variants grouped by source item
  with status/language/variant/staleness badges and per-group generation
  (summarize / detail / rewrite / aim-at-posting / translate), plus
  activate (supersedes the slot), archive, edit, regenerate (AI
  variants), delete-with-confirm. The builder's context panel gains the
  per-CV "Prefer synthesized items" toggle (`synth_mode`), and lint
  surfaces the synth signals. All strings cataloged (`cvSynth.*` i18n
  group); E2E smoke covers the library entry + empty state.
- **Synthesized CV items: copilot tools (plan 62.4).** Five registry
  tools give the CV-builder copilot (and the 41b MCP readers, which
  expose read-scope automatically) the variant lifecycle:
  `cv_synth_list` (with per-variant applicability verdicts vs a CV —
  applies / wrong_language / other_posting / stale /
  override_conflict / mode_off / orphaned), `cv_synth_read`,
  `cv_synth_generate` (draft-then-approve, all five actions),
  `cv_synth_update` (text + status; no delete tool — AI never deletes
  user content), `cv_synth_enable` (flip `synth_mode`). Write-scope
  mutators remain ownership-checked; reads land in the /mcp surface.
- **Synthesized CV items: builder integration + lint (plan 62.3).**
  Per-CV "Prefer synthesized items" toggle on the context selection
  (`synth_mode: off | prefer`, off keeps existing CVs byte-compatible).
  In prefer mode the context engine swaps matched active variants' text
  into the snapshot before editor overrides (override > synth > source
  always holds), and the compiled version trace records which variant
  applied per item (`synth_applied` in `context_resolution`). Lint
  gains deterministic signals: `synth_available` (matching variants
  exist while the mode is off), `synth_share` (how much of the CV is
  synthesized), `synth_stale` (a variant's source changed since
  generation) and `synth_conflict` (a manual override beats a variant).
- **Synthesized CV items: AI generation (plan 62.2).** New `cv_synth`
  AI task + draft pipeline: grounded summarize / detail / restyle /
  posting-fit over the request's own context items (require `cost`
  refs the user requested; out-of-allowlist draft items are dropped,
  never trusted), translations as first-class language siblings
  (`translate` reuses the master's source hashes so staleness stays
  truthful), regenerate for stored AI variants, bulk runs (light /
  ≤5 refs inline, 5+ ride the `cv_synth` background job), and a
  "variants ready for review" notification through the funnel.
  Draft-then-approve: activation still supersedes the slot's previous
  owner (draft or active).
- **Synthesized CV items: the variant library backend (plan 62.1).**
  New `cv_synth_items` table — a user-level library of AI-written or
  manual variants over CV context items, with typed source refs,
  per-source content hashes (staleness detection), variant slots
  (`variant_key` × optional posting), and draft/active/archive
  lifecycle (activating one variant auto-archives its slot siblings).
  Library CRUD under `/api/v1/cv/synth` with filters (status, source,
  posting, language, staleness) and computed state (`stale` /
  `orphaned`); deterministic match precedence (active → language →
  posting-scoped beats generic → `default` first) lands with the
  resolution hook in 62.3. The user data export now includes the
  library (`cv_synth_items.json`). AI generation arrives in 62.2.
- **Languages are no longer a closed list — any language can be added
  on demand.** The profile's language picker is a searchable combobox
  with create ("Add language “Punjabi”"): type any language not in the
  curated list and it saves as the entry (normalized to lowercase), and
  CV-import AI extraction accepts freeform code/name values the same
  way. The curated maps grew to 30 languages (Hindi, Urdu, Persian,
  Romanian, Ukrainian, Vietnamese, …), the CV renderer's name fallback
  now title-cases full-name codes ("hindi" → "Hindi" instead of
  "HINDI"), and everything renders identically through the same
  vocabulary.
- **Experience workspace groups read better and act per category.**
  Kind headers carry their kind icon, an accent count pill and their
  own "+ Add" button that opens the editor pre-set to that kind
  (language keeps the global entry point on the toolbar). Item cards
  got richer previews: a two-line description clamp, skill chips (first
  four + overflow tag), kind icon badge, and hover-stable duplicate and
  delete actions; grouping collapses under the same chevron as before.

### Changed
- **Explicit language link on certifications ("Proves language").**
  Certifications get an optional 2–3-letter `language_code` (schema,
  API + editor dropdown in the certifications card: "Proves language:
  English ▾"). When set, the CV renderer's languages block claims that
  certificate inline and the languages/Certifications dedupe honors it
  even when no exam keyword is present — the explicit link outranks
  the derived exam matcher, which stays as fallback for certificates
  without one (e.g. historic imports). The profile language selector
  also widens from 10 to 16 codes (PT/NL/SV/PL/JA/KO included),
  matching the CV renderer's name map so imported languages are
  editable everywhere. Migration `0026` adds the nullable column
  (round-trip tested).

### Fixed
- **Links read like print, not web chips.** A "Github" icon-and-label
  chip is useless on paper — link display now shows the actual address
  (`github.com/<handle>`: scheme stripped, no `www`/query/trailing
  slash), as `<icon> address`, still wired as a real `<a href>` where
  clickable. A custom label prints as `Label (address)`. Markdown/DOCX
  exports render the same print-first text, and links whose URL fails
  the href allowlist are not printed at all (previously the label
  survived as text). Header line estimation follows the real address
  length instead of the label.

### Fixed
- **CV import parses education dates and levels properly.** Date
  parsing no longer drops what real CVs contain: full dates
  (2020-03-15), dot/slash separators, MM/YYYY and month names ("Sep
  2020") all parse; missing gaps default (year-only → January,
  month-only → day 1) instead of silently landing nowhere. Education
  level resolution is a curated matcher: known vocabulary (BSc/MBA/PhD,
  high school variants, …) wins, then degree-word inference — a plain
  "University of …" entry no longer lands in High school (it maps to
  Bachelor), vocational/technical institutions map to Vocational, and
  truly unknown stays at the documented high_school fallback. The
  extraction prompt now states the allowed level vocabulary (generated
  from the same matcher — it can't drift), and the review card shows
  mapped labels ("Bachelor", not freeform strings) plus a "level
  unknown — defaults to High school" hint and prettifies dates ("Sep
  2020 – Mar 2020").

### Added
- **Multi-page previews show you where the page turns.** The builder
  preview now lays all pages out stacked with dashed accent page-break
  markers ("Page 2", "Page 3"…) instead of hiding the overflow inside a
  one-page scroll box; the driver is the renderer's estimate until a PDF
  export records the real count.

### Fixed
- **Two-column CVs paginate correctly in print.** The flex sidebar
  layout — which Chromium refuses to fragment across print pages,
  clipping sidebar CVs longer than a page — is now a table-based layout
  that breaks cleanly onto every page (the colored sidebar background
  continues on each page). Page estimation follows suit: a two-column
  CV fills max(main, sidebar) pages instead of the sum, so shrink and
  truncate now fire based on the column that actually overflows, and
  truncation drops whole blocks from that column directly.
- **The exported PDF's real page count is measured and reconciled.**
  Each PDF export reads the actual page count out of the Chromium
  document and stamps it onto the compiled version (`pages_actual` +
  over-budget flag); the lint report surfaces `pages_actual` next to
  the estimate — estimates inform the preview, exports establish the
  truth. Full page indicators in the copilot's visual review now base
  on the estimate as before; PDF page capacity never silently exceeds
  `max_pages` without the over-budget flag being recorded.
- **Multi-page CVs overflow cleanly instead of ugly.** The renderer's
  page estimation now counts the content that actually overflows — long
  item descriptions and achievement bullets were previously free — with
  column-aware wrap math (sidebar columns wrap ~3× sooner than the main
  column, font-size and page-size aware), so `shrink`/`truncate` fire
  before the PDF really spills. Print output gains fragmentation rules:
  section headings no longer strand at page bottoms (`break-after:
  avoid`) and list items, achievement bullets, chip rows, skill bars,
  the header row and card containers stay whole across page breaks
  (`break-inside: avoid`). Sidebar layouts longer than one page remain
  the known limitation (flex columns don't fragment in print) — that
  structural fix comes with the measure-actual-pages pass.

### Added
- **Languages sections read like a human wrote them — and proficiency
  certificates print once.** Language entries resolve to human names
  ("English", not "EN") with a representative CEFR band ("Advanced (C1)").
  The `languages` block grows real presentation options in the Sections
  panel: Chips vs. Lines format, a "Show CEFR band" toggle, and a "latest
  proficiency certificate" toggle that appends the newest
  language-proficiency certificate inline — English — Advanced (C1) ·
  EF SET Proficiency Certificate, Jun 2025. Detection runs on a curated
  exam registry (TOEFL, IELTS, Cambridge, Goethe, DELF/DALF, DELE, JLPT,
  TOPIK, HSK, EF SET… plus generic "%Language% Proficiency" naming), and
  the certifications `items` block gains a "Hide proficiency
  certificates" toggle so the same certificate never prints twice in one
  CV. Markdown/DOCX/text exports render the same enriched lines and
  share the dedupe behavior; existing templates render exactly as they
  did before (all new options off by default).
- **CV Studio: section areas are now a first-class builder surface.**
  Sidebar templates declare their template areas (Left panel / Main —
  side-aware), and the Sections panel groups sections under area
  headers with per-area counts, dashed drop-to-fill empty zones, and
  drag between groups (in grouped view the group shell is the source of
  truth — no per-card chip, so titles show in full). Each group footer
  carries its own "+ Add section" button that opens the card picker
  pre-locked to that area; the global Add picker keeps an "Add to"
  toggle for the whole dialog. Duplicate keeps a section's area. The
  builder copilot digest exposes each block's area and `add_block`
  accepts an optional `area` (`main`/`sidebar`); the renderer honors
  the new `area` mark with the legacy `column` as fallback.

### Fixed
- Sidebar sections no longer silently collapse into the main column
  when a CV's working content was saved (duplicate/drag paths dropped
  the sidebar mark); block placement is now a stable `area` key.

### Changed
- **Profile → Import from CV is now a first-class destination.**
  The Overview entry is a status panel ("3 CVs on file · latest:
  …, Imported") instead of a bare button, and every processed CV is a
  clickable link to its own page at `/profile/import/:id`: applied and
  discarded drafts open a read-only view of what was extracted —
  sections with confidence pills and evidence quotes (source-page
  grounding included) plus the apply report — with re-process,
  download and delete on the spot; pending drafts open the review flow
  straight from the URL.
- **Import history rows got deeper links.** The CV filename opens the
  per-CV detail; Review jumps into that document's review flow;
  re-processing from the detail view re-parses and lands in review.
- **Projects get their own CV section — and the experience list groups
  by kind.** A `projects` context source (the block system already
  validated the key) and an optional `kinds` filter on `items` blocks
  let templates render Work Experience (jobs, internships, freelance,
  volunteering) and Projects as separate sections; a new bank template
  "ATS Classic — Work & Projects" demonstrates the split, existing
  templates render unchanged. On `/profile/experience` the rail
  groups entries under collapsible kind headers with counts until a
  kind chip narrows the view.
- **Experience & Education workspaces get selection, bulk actions and
  filters.** Every entry card now has a select checkbox and a
  Duplicate action; selecting several swoops in a bulk bar (Select all
  · Set active · Set draft · Delete, delete with confirmation and the
  same 8-second multi-undo). Both workspaces gain a filter panel:
  search by title/organization (education: program/institution),
  Active/Drafts status segments, and kind chips on Experience (level
  chips on the education tab, kind chips on achievements).
- **Where a CV import landed is now traceable.** Applying a CV records
  each created entity in the new `cv_intake_applied` ledger
  (migration 0025), and the per-CV detail view for processed CVs shows
  a "Landed in your profile" row of deep links — Basics → profile,
  Skills → the profile skills section, Experience / Education /
  Certifications / Achievements → their workspaces.
- **Imported items are active unless you say otherwise.** The review
  step is the approval: applied experience/education/certifications/
  achievements now land "active" (visible to CV generation, stage
  heuristics and readiness) instead of silently parked as drafts.
  Want drafts? "Save as drafts" in the review footer drafts everything,
  and every status-bearing item carries its own Draft/Active chip.
- **CV Studio reaches the import workspace.** The New CV modal gains a
  "Import from CV" mode that jumps to `/profile/import`, and CV Studio
  shows an "Imported CVs (sources)" panel with the latest uploaded
  source files and their status, linking into the per-CV pages. The
  success phase of an import now also lists the landed-in-profile
  links right away.

## [v0.7.1] - 2026-09-10

### Changed
- **Sidebar reconciliation** — the shell drops from 14 to 11
  items around one rule: surfaces that write the profile nest under
  Profile, activities stay top-level.
  - **Assessment** is now a profile workspace at `/profile/assessment`
    (rail entry + summary card on the profile page); `/assessment`
    redirects.
  - **Universities** become a fourth Catalog subtab
    (`/catalog/universities`, gated on the universities feature flag as
    before); list and detail routes moved, old URLs redirect.
  - **Live + Explore merge into one Postings surface**
    (`/postings`) with Feed | Search subtabs; `/explore` redirects to
    `/postings/search`. All feeds, filters, facets and saved searches
    keep working unchanged.
- **"Generate jobs with AI" is now a subtab of the Job Catalog**
  (`/catalog/generate`) instead of a standalone page — browse, then
  invent, in one place. The catalog tabs (Tree | Graph | Generate) are
  real URLs, so views are deep-linkable; `/generate` redirects to the
  new location (sidebar and Dashboard quick links updated).
  `/catalog?family=<key>` deep links now open the catalog pre-filtered to
  that family (previously silently ignored).

### Fixed
- Red `ruff format --check` CI gate — a missing trailing comma in
  `backend/app/ai/chat_models.py` failed the lint job.
- Stray "everyone" text rendered after the review-queue heading on the
  job-generation page; hardcoded "Review details" / "Publish all" labels
  are localized now.

---

Release history lives in [GitHub Releases](https://github.com/neuronection/career-assistant/releases)
(the pre-launch changelog was retired when the repository was republished;
tagged releases `v0.2.0` onward are listed there).
