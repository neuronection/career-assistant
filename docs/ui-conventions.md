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
- Structure: **toolbar row → three-pane grid**
  `lg:grid-cols-[minmax(230px,280px)_minmax(0,1fr)_minmax(290px,340px)]`
  (context | canvas hero | inspector; two panes for the template editor).
- Panes are rounded `border border-[var(--as-border)] bg-[var(--as-surface)]`
  cards; the canvas pane is the hero (largest, live preview).
- Below `lg`, a **pane switcher** (segmented buttons, `lg:hidden`,
  `data-testid="pane-switcher"`) toggles one pane at a time — every
  feature stays reachable on tablet/mobile. Panes render with
  `` `${active ? "flex" : "hidden"} lg:flex` `` so CSS decides.
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
- `SectionsPanel` — the card pattern for ordered lists: drag handle,
  kind icon, inline title, gear-configured collapsible panel
  (`cv-collapse` animation), duplicate/move/remove actions.
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
university parse).

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
