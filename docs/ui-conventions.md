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
  creates/patches a scope-`bullets` VARIANT pinned via the item's
  `:bullets` synth-pin slot (no CV-local override for achievements),
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
- **Catalog tree layout**: same `SettingsShell` recipe (plan 96) —
  top-level families as the rail (`data-testid="catalog-families"`,
  job counts as `trailing` nodes), content pane = search + recent
  searches + drill chips for the active family's children
  (`catalog-subfamilies`) + the job-card grid. The expanding tree is
  gone: selection + one-level drill chips replace it, so the whole
  surface survives the dock and narrow widths via the container
  modes.
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
