# UI conventions

The app's product surfaces follow one modern design language, introduced
with the CV Studio workspace (plans 47–49, 2026-09). **Read this before
building or restyling any page** — the goal is that every new surface
looks like it belongs to the same product.

## 1. The workspace pattern (app-like pages)

Pages that are "tools" (CV builder `/cv/:id`, template style editor
`/cv/templates/:id`) render **full-bleed workspaces** instead of the
centered `max-w-7xl` column:

- `Layout.tsx` keeps a route allow-list (`useMatch`) of full-bleed
  paths; those render `flex min-h-0 flex-col … lg:h-full` so panes
  scroll independently and the page owns the full viewport height.
- Structure: **toolbar row → pane grid** (context | canvas hero |
  inspector; two panes for the template editor). Rail widths are
  per-page via the `ca-ws-grid` CSS var: default
  `minmax(260px,340px)`, `ca-ws-grid-narrow` `minmax(230px,280px)`
  (CvBuilder inspector), `ca-ws-grid-wide` `minmax(330px,400px)`
  (template editor side).
- Panes are rounded
  `border border-[var(--as-border)]` cards; the canvas pane is the hero
  (largest, live preview). **Elevation is a three-step ladder** (plan
  90): workspace panes are *sunken trays* (`bg-[var(--as-muted)]`),
  cards/inputs inside them float on `--as-surface`, popover-grade
  elements use `--as-surface-raised` — never give a tray and its
  contents the same background. The token ladder
  (`muted` tone-100 → `surface` tone-50 → `surface-raised` tone-0)
  already encodes this.
- Below the container breakpoint, a **pane switcher** (segmented
  buttons, `data-testid="pane-switcher"`) toggles one pane at a time —
  every feature stays reachable on tablet/mobile. Panes render with
  `` `${active ? "flex" : "hidden"}` `` plus the `ca-ws-pane` class so
  CSS decides. **Responsiveness is container-based, not viewport-based
  (plan 95):** the workspace root carries `ca-workspace`
  (`container-type: inline-size`); `ca-ws-grid` / `ca-ws-switcher` /
  `ca-ws-pane` flip their layout in an `@container (min-width: 48rem)`
  block in `index.css` (after the utilities — cascade wins). Viewport
  `lg:` classes cannot see the chat dock stealing width from the page
  column, container queries can. Experience/Education/Interviews are
  the reference pages. The same rule drives the library
  `SettingsShell` (Profile/Settings rails): its chip-row ↔ rail modes
  key off the shell's own width.
- The inspector has **three tabs** (plans 85–87), ordered Sections →
  Context → Design with **Sections as the default** (cover letters
  default to Context, where the brief lives) — each a real workspace;
  one-off AI actions are NOT a tab
  (they live in the toolbar's `AiToolbarCluster` next to "Ask AI") and
  read-only reports are NOT tabs either: the lint report opens from the
  toolbar's ATS score chip (`ats-chip` → popover with score, pass/warn/
  fail summary and the checks list). The switcher is a **segmented
  control with a sliding thumb** (plan 88, `.cv-tab-thumb` in
  motion.css, proper `role="tablist"` + roving-focus arrows) — never a
  dropdown: tab state must be visible at a glance. The Context panel
  follows the same rule (plan 89): a coverage summary strip
  (`context-summary`, "N / M items on the CV"), group pills showing
  `included/total` (accent-tinted when fully included), the library
  `CheckIndicator` for the tri-state group header (role=checkbox with
  `aria-checked="mixed"` — never a switch), and empty groups surface
  their hint without expansion. The tab is also EDITABLE over profile
  data (plan 105): groups with an editor kind carry a `+` create
  button (`context-add-{key}`; empty groups repeat it as an "Add …"
  hint row), focusable item rows carry a pencil
  (`context-edit-item-{source}:{id}` → `EntityEditorModal`) and an
  external-link (`context-open-item-…` → the entry's workspace with
  `?focus=`), card-backed groups (skills/languages/interests/basics/
  objective) get a group-level profile link instead — affordances are
  always visible, never hover-reveal, and the CV-specific variant
  actions stay in their sub-row. Experience-kind rows add a fourth
  affordance, the plan-106 **Bullets editor** (`context-bullets-…` →
  `ItemBulletsEditorModal`): the two-layer bullets model — saving
  creates/patches a scope-`bullets` VARIANT pinned via the item's ONE
  `synth_pins["{source}:{id}"]` slot (plan 110 collapsed the old
  `:bullets` suffix; the plain key is the only form, no CV-local
  override for achievements),
  with the resolved snapshot list as base, an "Edited for this CV"
  chip, Reset-to-profile (unpin), a resolved
  "on the CV now" head, and AI bullets landing as ephemeral
  keep/discard chips (never auto-applied; generate-fill rides the
  bullet action with the plan-103 dirty-guard). The modal hosts the
  real workspace
  editors (one source, no re-rolled forms); saves bump the plan-104
  live-sync channel with a `local` origin, which refreshes context
  sources, preview and staleness without the "Profile changed" toast.
  "How my CV looks"
  lives in ONE Design tab — template card (picker + Browse/Customize +
  meta), Style section (tokens + page size), profile photo (resume
  only), printed review — over a pinned Apply/Reset footer
  (`design-scroll` scrolls, `design-footer` stays). Never split a single
  mental task across tabs; never give ephemeral actions or passive
  reports a persistent pane — toolbar chip/button + popover or modal,
  matched to content weight.
- Content pages (lists, dashboards) stay in the centered column.

## 2. Shared primitives — never re-roll controls

`components/cv/formPrimitives.tsx` is the control vocabulary (extracted
so the builder and the template editor share one source):

- `ToggleRow` (animated `as-switch`), `StepperRow` (clamped −/+ with
  `aria-label`s), `SegmentedRow` (pill radio group), `ChipTogglesRow`,
  `SelectField`, `RangeField`, `FieldLabel`.
- Ranges in steppers **must match the backend pydantic `ge/le` bounds**
  client-side; config changes autosave through the standard debounced
  patch and remain undoable.

Pickers/cards that follow the same recipe:

- `BlockTypePicker` — "Add X" opens a popover grid of **cards with mini
  schematic previews** (`TypePreview`), icon + name + one-line
  description; extend with `extraTypes` instead of adding raw selects.
- `SectionsPanel` — the card pattern for ordered lists (plan 84): a
  two-zone card — header row (drag handle with ArrowUp/Down keyboard move,
  accent icon tile, rename-in-place title for every kind that supports a
  `title` prop, always-visible eye → overflow `⋯` menu (move/duplicate/
  remove) → chevron) over a muted **config summary strip** (`summaryFor`,
  e.g. "Work Experience · List · Jan 2025 · max 10"); hover-reveal actions
  are banned here — discoverability over hover. The chevron (or the custom
  text "Edit" toggle) expands a `cv-collapse` config region grouped with
  small field-set labels ("Content" / "Display" / "Container"). A
  block-level `hidden` flag (the `area` precedent, renderer + exports +
  lint honor it) drives the eye toggle; hidden cards render dimmed with a
  "Hidden" summary. When the active template is sidebar-layout, the panel
  switches to an **area-grouped** variant (plan 61): solid group shells
  with a header row (icon, label, count pill, compact "+" opening the
  picker with `presetArea`), dashed accent border only while a drag hovers,
  and drop-target styling — sections drag across groups to reassign; the
  top Add-section picker keeps the "Add to" area toggle.
- Cards use tokens everywhere; hover = accent border + surface-raised.

When a second family app needs the primitives, promote
`formPrimitives.tsx` / `BlockTypePicker` into `@neuronection/assistant-ui`
(two-app rule) — they are on the promotion-candidates list.

### 2b. The intake review pattern

CV import (`components/intake/`) renders extraction drafts as grouped
review cards: section header with a tri-state select-all, per-item
`CheckIndicator`, confidence pill (`cv-intake-pill-{high,medium,low}`),
and the verbatim evidence quote — review-first, nothing applies without
a tick. Selections are controlled (`section → true | indices`); reuse
this recipe for any future extraction-review surface (posting extract,
university parse). Status-bearing sections (education, experience,
certifications, awards — `STATUS_SECTIONS` in `CvStatus.tsx`) carry a
per-item Draft/Active chip next to the confidence pill, plus the
review footer's global "Active items / Save as drafts" segmented
(`cv-intake-apply-mode`); the backend payloads are `selections` +
`drafts` (section → true | indices), **applied items are ACTIVE by
default — the review ticks are the user's approval**. The basics
section is field-granular (`BasicsReview` in
`SuggestionReviewList.tsx`): each contact field renders its own row,
and where the profile already holds a different value the row turns
amber with "Now: …" and an explicit Keep/Replace segmented control
(`basics-decision-{field}`; default Keep, sent as `basics_overwrite`
on apply) — never silently overwrite existing profile data, and reuse
this field-level conflict recipe for any future merge surface. The
same list renders in `readOnly` mode (no
checkboxes/counts, pills + evidence kept) — the browse view of what a
processed CV contained on the per-CV detail route
(`/profile/import/:id`, clickable from the history rows), together
with the apply report and a "Landed in your profile" row of deep
links (`cv-applied-link-*`) driven by the `cv_intake_applied`
ledger surfaced on the draft endpoint's `applied` field; the link
map lives in `CvDraftViewer.APPLIED_ENTITY_LINKS`. Shared CV
status vocabulary (`StatusChip`, `statusLabelKey`, `reportSummary`,
`ReportLines`) lives in `components/intake/CvStatus.tsx`; the Profile
overview's import panel (`import-cv-panel` with a live
`import-cv-status` line) consumes the same label keys.

### 2c. The item-card density pattern (plan 112, 2026-09)

Any surface that renders a *list* of items (a HITL proposal's diff rows,
an experience/education card, a profile summary card) is either
**compact** or **full** — one vocabulary, never a per-surface ad-hoc cap:

- **`density: "compact" | "full"`** is a presentational prop, no state.
  The library `chat-hitl` card (`HitlProposalCard`, `FieldDiff`,
  `FieldSummary`) takes it; app cards (`ExperienceItemCard`) mirror it.
  Default is always `full`, so a consumer that never passes it renders
  exactly as before.
- **The caller derives density from context, never from a user
  preference.** Chat: `variant === "page" ? "full" : "compact"`
  (`ChatWidget.tsx` → `MessageList` → `ProposalCards`), because the
  bubble/docked panes are space-constrained; the Preview modal is always
  `full`.
- **Compact truncates but never silently.** The library's `CappedRows`
  caps at 3 rows behind a "Show all N fields" expander
  (`data-hitl-action="toggle-rows"`); summary cards use a `+N more`
  link to the full workspace (experience group + education). A count
  badge tells the user how many exist.
- **Full shows everything the item carries.** For experience that means
  the un-clamped description, all achievements, every skill tag with its
  role/level, links, hours and on-site policy; for education, grade
  band, focus subjects, description and in-progress.
- **Links are user input.** Route every rendered URL through
  `safeExternalUrl` (`lib/url.ts` — absolute `http(s)` only, drops
  `javascript:`/`data:`/relative) and render
  `target="_blank" rel="noopener noreferrer"`. Anchors live *outside*
  the card's `<button>` — never nest an `<a>` inside a button.

### 2e. The item-card system (plan 140, 2026-10-28)

Every list surface that renders an item card (`/postings`, `/catalog`,
`/rankings`, `/companies`) uses the module in `components/cards/` — same
grammar, different content. The shell (`ItemCardShell`) owns the surface,
hover (accent border + `--as-surface-raised`), the single root `onClick`
(the title is a `<button>` **without** its own handler — its click bubbles;
action slots stop propagation), `density`/`data-state`, and the
`ca-item-card` container (the action column stacks by **container** width,
never a viewport breakpoint — the chat dock narrows the column).

**Metrics follow the card's own width** (plan 191): one node
(`.ca-job-metrics`) renders the open-roles number + caption + salary as a
full-width inline strip on a narrow card and as the posting-anatomy rail on
the leading edge at a card container ≥ 26rem — CSS-flipped in
`index.css`, never a duplicated DOM, a `compact`-only branch or a viewport
breakpoint. **The catalog type floor is 11px**: kickers are 11px uppercase
(0.06em tracking), meta/footer 12px, the family line 12.5px, descriptions
14px clamped to three lines, and titles wrap to two lines instead of
single-line truncating. Chips never wrap internally — `SkillTag` and badge
chips are `whitespace-nowrap` with a `max-w-[12rem]` truncate guard, so
`fitChips` measurement stays honest.

Information is **three tiers**, never one chip soup:

1. **Spec slots** (`CardSpec`, `SPEC_ORDER`) — closed vocabularies in a
   canonical order, rendered as faint uppercase label + value, **no pill**:
   mode · level · contract · hours · salary · education · closes. A slot
   renders only when the value exists.
   - **Nominal values** (mode, contract, education) are plain text in one
     neutral tone with a small glyph that carries the mapping where the
     vocabulary has one (mode: globe / house / building — `MODE_ICON`) —
     never a per-value hue.
   - **Ordinal values** (level) use the intensity cue: a 1–5 dot scale in
     the accent (`seniorityScale`: intern 1 → senior 4, lead/principal 5),
     rendered by `CardSpec` as `spec-scale-{key}` with `data-filled`.
   - Hue is reserved for **state** (fit band, warning, closed) and for the
     skill **heat ramp**: "amber" must never mean both "hybrid" and
     "closing soon".
2. **Tags** (`ChipRow`) — open vocabularies only (skills, interests,
   industry tags). Skills render **all** of them, server-ordered
   must-have → nice-to-have → bonus → level → label; the row clamps to
   **two rows** and the **last chip of row two is `+N`** — the count of
   the rest, which is also the expander. Measurement is width-based
   (`fitChips` + `ResizeObserver`); hidden chips stay in the DOM (sr-only)
   for search, print and screen readers. **No fade/mask** on the clipped
   row: a faded second row reads as disabled.
3. **State markers** (`CardState`) — binary facts as a compact icon (+
   optional label), never a pill: **seen** = one muted double-check in the
   kicker plus a 3 px neutral rail on the card's leading edge
   (`[data-seen="true"]::before` in `index.css` — a read marker, not a
   state hue: accent stays hover/interactive and fit bands stay the only
   colour language; unseen renders nothing, the normal state is silent,
   and cards are never dimmed). While unseen, the *same kicker slot*
   carries the `posting-mark-seen` action (a quiet text action with an
   accent check) — state and action share one slot, so clicking it turns
   the slot into the seen mark in place; seen is one-way (no un-see
   endpoint), which is why it is not a toggle. **closed** =
   neutral lock + close date tooltip,
   with the whole card desaturated via `data-state="closed"` (tokens, not
   `filter: grayscale`, so contrast holds) and Apply disabled; saved /
   applied ride the kicker; **partial details** = info dot (extraction
   confidence, never "unread"); "closes in n d" is a spec slot while the
   posting is still open.

**Scores** are one component family: `ScoreBubble` (SVG ring, banded by
`scoreTone`; numeric sizes — 40/44/52/72 in use) and `ScoreBreakdown`
(dimension bars, banded or neutral; `defaultWeight` hides the neutral
weight, `alwaysShowWeight` keeps every weight) — never a naked number.
**Org identity** is `OrgAvatar` (deterministic initials tile, no external
favicons — CSP) + a `/companies/:key` link; its tint pairs are inline
data-driven swatches, the documented exception to the token-only rule.

**Skill chips** (`SkillTag`) carry one number as heat and nothing else:
the 1–10 requirement (or, where supplied, the per-skill match) as a 6 px
bullet — **cold** 1–3 (`--as-muted-fg`), **warm** 4–6 (`--as-warning`),
**hot** 7–10 (`--ca-heat-hot`) — plus the number. Priority is **not**
rendered on the chip: it lives in the order and in the detail page's
group headings. Unmapped skills get a dashed border (data quality, not
ranking).

Testids are contracts: `posting-card`/`posting-details`/`posting-title`/
`posting-apply`/`posting-save`/`posting-hide`/`posting-mark-seen`/
`posting-provenance`/
`posting-coverage`/`posting-seen`/`posting-closed`/`posting-partial`/
`posting-details-pending`, `job-card`/`job-title`/`education-chip`,
`scores-{code}`/`breakdown-toggle-{code}`/`compare-add-{code}`,
`score-ring` (the bubble), `fit-breakdown`, `match-card`/`match-score`,
`skill-tag`/`skill-heat`. Assert `data-tone`/`data-heat`/`data-score` —
never colour classes.

## 2a. The profile section-card pattern (plans 50, 2026-09)

Profile data entry (profile page `/profile`, onboarding wizard
`/onboarding`, assessment reuse) renders **one shared set of section
components** — `components/profile/sections/*Card.tsx`. A card owns its
draft; no page keeps a parallel form state. Never reintroduce a
page-local form for a profile section.

- **`ProfileSectionCard`** — the card shell: title, description,
  completeness dot (`complete`), save-state indicator
  (`Saved ✓ / Saving… / Unsaved changes / Couldn't save`), and
  `variant="page" | "onboarding"` (onboarding drops the border and adds
  guiding copy). `data-testid="profile-section-{name}"`.
- **`useSectionDraft`** — draft + dirty tracking + debounced autosave
  (500ms, timer cleared on unmount — the builder's pattern).
  `mode="autosave"` on the profile page; `mode="manual"` in the wizard,
  where "Save & continue" flushes via the card ref
  (`SectionCardHandle.save()` returns `false` when invalid so the
  wizard can block). Payloads are **structured section objects** —
  never JSON strings.
- **Save semantics**: profile sections autosave (per-section PUT
  partials); discrete records (experience entries, skills) use explicit
  saves. Untouched drafts never PUT (payload-JSON comparison).
- **Validation**: tiny plain-function rules (`requiredRule`,
  `emailRule`, `rangeRule`) exported from `formPrimitives.tsx`; errors
  render in `FormRow`/field `error` slots and gate autosave. Bounds
  mirror the backend pydantic `ge/le`.
- **Option vocabularies** (stages, education, GPA bands, languages,
  conditions, work scales) live once in
  `components/profile/sections/options.ts` — the wizard, profile and
  any future surface must import from there, not re-declare labels.
- **Skills are open vocabulary**: skill pickers use the library
  `allowCreate` combobox rows (`Add skill "…"`), slug free text with
  `lib/slug.ts`, and rely on the backend find-or-propose contract
  (unknown keys become `proposed` rows — `PUT /me/skills` and
  experience items alike). Selecting from the picker adds immediately
  (profile: level 5, no extra button); picking an already-listed skill
  never resets its level.
- **Profile page layout**: the library `SettingsShell` two-pane with a
  sticky rail (`data-testid="section-rail"`), completeness dots per
  entry (nav `trailing` nodes), and `#/hash` deep links per section.
  Experience appears as a summary card linking to
  `/profile/experience` — editing lives only in the experience
  workspace, which has no top-level sidebar entry.
- **Catalog tree layout**: the `/postings` page template (plan 191). The
  page body carries `ca-stats-page`; `.ca-stats-cols` renders filter rail |
  results | recent searches — one column below 64rem of page width, where the
  filter card stacks above the results and the recent panel follows them
  (container query, plan-95 rule; never a `lg:` switch). The left
  `ca-stats-rail` is the **one family surface**: its `Job family` section
  carries the facet counts and the tri-state cycle, and the `family` URL
  parameter keeps its meaning so old links still filter. The middle column
  carries `ca-card-page` + search, drill chips for the active family's
  children (`catalog-subfamilies`), the count/active-chips/sort strip and
  `.ca-card-grid` (1 → 2 at 32rem → 3 at 54rem of the RESULTS column, not
  the viewport). The right rail is the shared `RecentSearches` panel: at
  most four real records, `filters only · 0 results` rows pruned, nothing
  rendered when empty. No viewport column classes (`sm:`/`lg:`/`xl:`) on the
  page; the type floor and chip rules live in §2e.
- **Experience workspace** (`/profile/experience`, full-bleed, nested
  under Profile): master-detail
  rail + editor pane, `pane-switcher` below `lg` with focus moved into
  the target pane, optimistic save/delete with an `UndoNotice` (8s;
  undo re-POSTs the held snapshot → new id), dirty-guard
  `ConfirmationModal` on switches, collapsible derivation panel with an
  explicit Apply. Testids: `experience-list`, `experience-editor`,
  `experience-item-{id}`, `add-experience`, `save-experience`,
  `delete-experience-{id}`, `undo-experience`, `derivation-panel`,
  `apply-derivation`.
- **Workspace list mechanics (both workspaces)** — shared
  `components/profile/BulkTools.tsx`: a per-card `SelectionToggle`
  (library `CheckIndicator`, placed outside the card's open-button) and
  the `BulkBar` over the library `SelectionBar` (hidden at 0
  selected): Select all · Set active · Set draft · Delete, delete via a
  confirm modal + the multi-entry `UndoNotice` (undo re-POSTs each
  snapshot). Card `Duplicate` re-creates from the same toIn/form
  snapshot with a "(copy)" suffix. Client-side `filters` (search /
  status segmented / kind or level `FilterChips`
  `{page}-search`, `-filter-{all|active|draft}`, `-kind-{value}`;
  empty state: "No entries match these filters.").
- **Experience kind groups** — with no kind chip selected, the
  experience rail renders collapsible per-kind group headers (counts,
  `experience-group-{kind}` + `-toggle-{kind}`); the kind chips switch
  to a narrow flat view. On the template side, the CV context engine
  registers a `projects` source and `items` blocks accept a `kinds`
  filter, so templates can split Work Experience / Projects sections
  without touching the data model.
- **Education workspace** (`/profile/education`, full-bleed, nested
  under Profile: the same master-detail recipe over the
  education/certification entities, with an entity toggle
  (Education | Certifications) in the toolbar. Editors follow the
  experience-editor shape: constrained `max-w-2xl` column, sticky
  header (title + status) and sticky save bar. Institution picker
  searches the universities catalog with `allowCreate` free-text
  fallback (selected ids persist as optional FKs); departments list
  only for the chosen catalog university. Testids: `education-page`,
  `education-toolbar`, `education-back`, `education-derived`,
  `education-entity-{education|certifications}`, `education-list`,
  `education-item-{id}`, `education-editor`,
  `certification-editor`, `save-education`, `save-certification`,
  `undo-education`, `add-education`.
- **Achievements tab**: the education workspace grows a
  third entity (`education-entity-achievements`) — same rail cards
  (kind icons, draft/source chips), same editor skeleton
  (`achievement-editor`, `save-achievement`), undo + dirty-guard
  shared.
- **Studio-adjacent editing (plan 105)**: `lib/entityLinks.ts` is the
  ONE map from CV context sources (and intake entity types) to profile
  homes, editor kinds and deep links — never build a second
  source→route table. The experience workspace accepts `?focus=<id>`
  and education `?entity=…&focus=<id>`: the entry opens in its editor
  with a one-shot accent ring (`experience-focus-highlight` /
  `education-focus-highlight`), params stripped on apply. The
  Studio's `EntityEditorModal` composes the extracted editors with
  their `EMPTY_*` forms/validators and kind presets per source
  (experience→job, projects→project, volunteer→volunteer); payload
  builders (`experienceToIn`/`experienceItemToIn` and the education
  triple) live next to the editors so page and modal cannot drift.
  Skills are card-backed (context item ids are taxonomy UUIDs, not
  user-skill row ids) — the modal hosts `SkillsCard` whole.
- **Interviews workspace** (`/interviews`, — top-level sidebar
  entry, not nested under Profile): master-detail over practice
  sessions. Rail cards carry status chips (library `Badge` variants:
  planned/active/completed/abandoned) and rubric aggregates; the detail
  pane is a constrained `max-w-2xl` column with the question-plan
  editor (reorder/remove with `plan-{up|down|remove}-{id}`, answered
  questions locked, `save-plan`) and the debrief panel
  (`debrief-aggregate`, `debrief-resources`, `retry-weak`). Practice
  hands off to the shared chatbot (`openInterviewChat` → docked mode) —
  the page never embeds its own transcript. Creation rides a modal
  (`add-interview`, `interview-kind`, `interview-job`,
  `create-interview`); the posting-detail CTA
  (`practice-interview-posting`) creates + starts + jumps straight to
  chat.

## 2f. Settings surfaces (plan 148)

Every settings page composes from the app kit in `components/settings/`
(never re-roll page-local cards):

- **`SettingsPage`** — icon + title + description + status chips, then an
  optional **in-page section rail** (sticky anchor nav; exists only ≥62rem
  of PAGE-column width — `ca-settings` container queries, plan-95 law) and
  the content column (reading measure caps at 52rem ≥68rem so wide
  displays stay readable). `/settings` renders full-bleed (Layout
  allow-list) so those breakpoints engage on real displays; the shell
  is a flex child — width is explicit (auto margins would disable
  stretch), capped and centered at 100rem on ultrawide.
- **`SettingsSectionCard`** — icon tile, title, description, badge slots
  (incl. `adminOnly`), `summary` chip strip, `footer` actions, optional
  `collapsible` body (`cv-collapse`), `variant="danger"` for destructive
  zones. Testids `settings-section-{name}` (+`-toggle`/`-body`).
- **Hybrid save contract**: switches/toggles save instantly (optimistic
  via `useOptimisticToggle` — rollback + failure flag), forms save
  explicitly; every card carries a `SaveStateIndicator`
  (`Saved ✓ / Saving… / Unsaved changes / Couldn't save — Retry`,
  `aria-live`); drafts flow through `useSettingsDraft` (the profile
  `useSectionDraft` contract generalized — dirty tracking, payload-JSON
  compare so untouched drafts never PUT, unmount-safe debounce).
  Notices render IN the card that caused them; toasts only for
  cross-card events.
- **Navigation** (`config/settingsNav.ts`): rail display sections derive
  from the settings-map contract groups (app+user → Personal,
  ai/tools → AI & tools, automations → Automation, app+admin →
  Administration) via each item's `sectionKey`; `settingsMap.test.ts`
  pins both the derivation and the contiguous runs. The library
  `SettingsShell` renders the labels (chip mode hides them).

## 2g. The taxonomy listing pattern (plan 150)

Admin catalog listings (`/settings/taxonomy`, six URL-synced segments)
share one shape — reuse it for any review surface instead of re-rolling
raw tables (`TaxonomyList`, `TranslationsBoard`, `TaxonomyPathCards`,
`TaxonomyEnrichmentCards`):

- **Toolbar first**: debounced library `SearchInput` (no internal
  debounce — debounce app-side, 200 ms, reset the render window with
  each settled query), single-select filter pills **with counts**
  (rounded-full, `aria-pressed`, count in `tabular-nums`), and the
  primary action as the toolbar slot.
- **Groups are the review axis**: collapsible sections with a per-group
  lucide icon + count pill (`taxonomy-*-group-*` testids); empty groups
  hide. Interests group by category, skills by status (proposed first —
  triage order), translations by entity kind. Rows/cards carry their own
  category/kind icon.
- **Rows and cards are the click target** (Enter works; row testids key
  on the stable key). Destructive or rare actions live in the details
  drawer or on the review card — never inline on the row, and hover
  reveals nothing destructive.
- **Details drawer**: ONE generalized `EntityDetailsDrawer` (PanelModal —
  a centered modal that width-caps on desktop and goes full-screen below
  `sm`; never a side sheet) with per-kind adapters;
  the skills adapter keeps the richer stats/history surface.
- **Bulk**: `BulkBar`/`SelectionToggle` (per-id endpoints loop client-side
  with per-item outcomes: successes summarized, failures listed — the
  plan-144 report). The checkbox is a SIBLING of the row button (a
  button never nests a button). Select-all keeps the plan-144
  "all loaded" semantics, scoped to the pill-selected partition where
  one exists (translations never batches across locales).
- **Growth**: an incremental render window + *Load more* (50/step) — a
  full fetched page never mounts as cards at once; a truncation hint
  states the page cap. Counts derive from ONE bounded fetch where the
  endpoint allows it (requests stay flat as filters grow).
- **States**: `EmptyState(icon, compact)` for empty AND no-match; the
  icon says what lives here (`Tags`, `Wrench`, `Route`, `Sparkles`,
  `Languages`, `Network`). Tab strips carry icons (`SegmentedTabs`
  icon prop) and keep a phone-floor width inside an `overflow-x-auto`
  wrapper — six labels scroll instead of squeezing. Loading stays the
  app's Spinner + label row (previews are the shimmer exception, §6).

## 2i. Filter chips — one cycle, one clear (plan 167)

Every filter chip follows the same contract (`TriStateChips` in
`components/filters/filterBits.tsx`), on every rail (`/postings`,
`/companies`):

- **off → include → exclude → off**: one click includes (accent), the
  second excludes (rose, `−` prefix), the third clears. Right-click jumps
  straight to exclude. Values are mutually exclusive across the pair of
  lists, and every mode drops the value from the other list.
- **A selected chip carries an ×** that clears it in one click — never
  make a user cycle back out of a state, and never hover-reveal it.
- **The pill is a wrapper with two sibling buttons** (value + remove):
  a `<button>` inside a `<button>` is invalid markup and swallows the
  inner click. Keep the value button's `data-testid` (its accessible name
  is the label + count) and give the remove button
  `data-testid="{testId}-clear"` + `aria-label` "Remove {label}".
- Chips that intentionally cannot be excluded (`allowExclude={false}`,
  e.g. the posted-window selector) cycle include → clear only, and still
  get the × — the visual contract stays identical.
- Binary state toggles (saved only, hide seen, deep-extracted) are
  checkboxes, not chips: their uncheck *is* the clear.
- **Exclude pickers are excluded chips too** (plan 166): the skills /
  organizations exclude lists keep the library `MultiSelectPicker`, but
  their selected chips carry `ca-picker-exclude` (rose bg + text, `−`
  prefix via `renderChipExtra`) so the same value reads the same whether
  it was excluded by a chip or by a picker. The wrapper class is the
  only lever — the library chip styling is internal, so scope the CSS to
  `[data-as="picker-chips"] > li` under that wrapper; never restyle the
  include pickers.

## 2j. The preset bar — saved views (plan 165)

A list page whose filter set is URL state gets a **preset bar** above the
results (`PresetBar`, `/postings` today):

- presets are **chips**, never a dropdown: apply on click, active state
  highlighted, a `⋯` menu per chip carrying the filter summary plus
  update/rename/delete (delete confirmed). Saving offers **Update
  {active}** instead of duplicating; names are unique per user.
- the preset is a **saved search** (`search_history.name`, `PATCH
  /me/searches/{id}`), not a second store — digests, RSS feeds and the
  scheduler already resolve saved searches by id.
- the save dialog shows the same human-readable summary the menu does, so
  what you are about to save is visible before it lands.

## 2h. Shareable list state — the URL is the state (plan 163)

A list page whose filters/order a user would want to reload, go back to
or send to someone else keeps that state **in the URL, not in
`useState`**:

- derive the page state from `useSearchParams` during render through an
  exported pure helper — `/postings` uses one vocabulary module
  (`features/catalog/exploreParams.ts`: `parseFilters` / `toParams` /
  `toSearchParams` / `countActive`, the same shape the API and saved
  searches use);
- handlers write the **canonical** search string with `replace: true`
  (no history spam, no dual state → no sync effect);
- one guarded mount effect drops unknown/malformed params and falls back
  to defaults — never error on a hand-edited link;
- omit defaults (`sort=fit` never appears), keep names that may contain
  commas as repeated params (`org=Acme%2C+Inc.`), and validate every
  closed vocabulary on parse.
- `/companies` is the second adopter (`features/companies/companiesParams.ts`):
  the directory rail, the search text, the status chips, the sort and the
  open-roles floor all ride the URL (`?status=new&work_mode=remote&min_open=5`),
  with the same parse → write → canonicalize contract.

### 2h+. Returning to a list keeps its view (plan 172)

URL state covers filters/order on back, but a remounted list also loses
its loaded pages and scroll height. The return contract on top of §2h:

- list pages remember their canonical search in session memory
  (`lib/listReturn.ts`, `rememberListSearch`); detail pages' back links
  (`/postings/:ref` → "All postings", `/companies/:key` → back) and
  detail-side list re-entries (hide) navigate to `listReturnHref(path)`
  carrying `{ listReturn: true }` state — never the bare path;
- the rendered list is snapshotted in session memory keyed by
  `profileEpoch|canonical-search` (`exploreListCache` /
  `companiesListCache`): a remount that is a **return** — POP, or a PUSH
  carrying the list-return state — restores items + cursor synchronously
  and skips the first fetch; any other navigation refetches page one as
  before. Any filter change refetches page one as before, and
  detail-side mutations keep the snapshot honest (hide drops the row,
  seen/saved patch it);
- `useMainScrollRestoration` journals `#main`'s scrollTop per
  `pathname+search`: POP restores it, a fresh PUSH starts at the top, a
  PUSH carrying `listReturn` restores it, REPLACE (filter patches, mount
  canonicalization) never moves it.

## 2d. Feature state (beta affordance)

`frontend/src/config/features.json` is the single feature-state table
(`key` = route prefix, `state` = `on` | `beta` | `hidden`, `since`,
`docs`). Navigation visibility (`config/nav.ts` via `isVisible`), the app
shell's beta banner, the demo tour (`scripts/ui-capture/scenes.mjs`) and
`backend/tests/test_docs_claims.py` all read it — they cannot disagree.
A route absent from the table is `on`.

- **Never hide a shipped page behind an easter egg.** `beta` means
  reachable with a visible chip; `hidden` is for a surface kept routable
  for deep links only. Changing a state is one registry edit plus the
  docs the gate names.
- The shell renders the chip + expectation line automatically
  (`components/BetaBanner.tsx`, testids `beta-banner` / `beta-chip`) for
  every `beta` route — pages never carry their own beta copy.
- The README feature-status table and `docs/user/<page>.md` follow the
  same registry; `test_docs_claims.py` fails when a claim drifts.

## 3. Design tokens & styling rules

- Semantic `--as-*` tokens only (`--as-surface`, `--as-border`,
  `--as-muted`, `--as-muted-fg`, `--as-accent`, `--as-fg`,
  `--as-z-modal`…). Pairing matters: `--as-muted` is a **surface**;
  faint *text* is `--as-muted-fg`. No raw hex except data-driven accent
  swatches (theme dots, gallery dots).
- Tailwind opacity modifiers on token colors don't work in TW3 — use
  `color-mix(in srgb, var(--as-accent) 12%, transparent)` instead.
- Buttons are library variants (`default`/`secondary`/`outline`/
  `ghost`/`destructive`); `size="sm"` inside toolbars/panes,
  icon-only `size="icon"` for compact actions — every icon button needs
  `aria-label` + `title`.
- CSS import order is sacred: `styles.css → index.css → styles/motion.css
  → theme.css` (theme last). Never reorder.

## 4. Motion

All motion lives in `src/styles/motion.css`, CSS-only, reducible:
`cv-pane-enter` (fade + 4px rise, 180ms) for panes/tab bodies,
`cv-collapse` (`grid-template-rows: 0fr/1fr`) for accordions,
`cv-drop-slot` (drag target outline + 120ms fade), `cv-shimmer` for
loading skeletons, `cv-toast-in`, `cv-slideover-in`, and the `as-switch`
transition. Global `prefers-reduced-motion: reduce` kills all of it.
New motion = add a keyframe there, not ad-hoc `animate-*` classes.

## 5. Drag & drop

Native HTML5 DnD with best-practice feedback: on `dragstart` build a
**card-shaped ghost** (`setDragImage`, grab point preserved, Firefox
`text/plain` payload), dim the source card (`opacity-40`), outline the
drop target (`cv-drop-slot`), reset on `dragend`. See `SectionsPanel`.
Guard `event.dataTransfer?.setDragImage` — jsdom has no drag images.

## 6. Previews & sandboxes

Every template/CV preview renders via authenticated axios fetch →
`srcDoc` + `sandbox=""` (iframes can't carry the Bearer token; CSP
`frame-ancestors 'none'` is correct — never weaken it). Loading previews
show `cv-shimmer`, never spinners.

Listing thumbnails are the exception: `CvThumbnail` uses a plain
`<img src="/api/v1/cv/{id}/preview.png?v={updated_at}">` — the backend
prints the first page through the PDF engine once, downscales and
disk-caches it by render hash, so a listing never mounts N live
iframes. `?v=` busts the browser cache after edits; a missing engine
degrades to the placeholder (503 → error state), never a broken card.

## 7. Testability contract

- Feature surfaces expose stable `data-testid`s: `preview-frame`,
  `builder-toolbar`, `pane-*`, `inspector-tab-*`, `context-toggle-*`,
  `add-block-*`, `section-card-*`, `stepper-*`, `toggle-*`,
  `use-template-*`, `edit-template-*`, `preview-template-*`, …
- jsdom DnD note: RTL `fireEvent.dragStart` has no usable
  `dataTransfer` — handlers must guard.
- Component tests that patch state via API mocks: make the **preview
  mock honor the last `patchCv`/`setContext` call** (like the real
  backend) — a static mock resurrects stale state and looks like an app
  bug.

## 8. Copy & tone

Plain English, sentence case for labels, `…` for trailing actions
("Browse…"), no jargon in empty states — offer the next action ("No
sections yet — add one above").
