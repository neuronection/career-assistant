# Changelog

All notable changes to **Career Assistant** are documented here.

## [Unreleased]

## [v0.13.0] - 2026-09-19

### Changed
- **Shared UI library updated to @neuronection/assistant-ui 0.43.0** — the
  About page's family grid gains the fourth member (Desktop Assistant):
  four cards in a 2×2 responsive grid.
- **Profile → Education adopts the segmented workspace pattern** — the
  entity switcher is the library SegmentedTabs with a new **All** view:
  every entry type (Education / Certifications / Achievements) renders
  as cards in one list, separated under count-labelled group headers.
  Editors, save, duplicate and delete are entity-aware regardless of
  the active tab; the Education-only summary, search and filters (and
  with them bulk actions) show on the dedicated Education tab.
- **Settings sub-tabs unified on the library SegmentedTabs** — the AI
  configuration tabs (Providers / Models / Tasks / Web, Web admin-only)
  and the taxonomy kind switcher (Interests / Skills / Paths /
  Enrichment) drop their hand-rolled, hard-coded-palette button strips
  for the same animated, keyboard-navigable segmented control used on
  the Experience workspace.
- **Profile → Overview separates "Profile completeness" from CV import**
  — the Import-from-CV strip no longer lives inside the completeness
  card; it is its own section led by the hook "Do you already have a
  CV? Use it to autofill your profile" (upload → we extract
  experience/education/skills → nothing lands without your tick).
- **Cover letters are gated off until the feature ships** — the
  "New cover letter" button in CV Studio and the "Draft cover letter"
  action on postings render disabled (with a "Coming soon" hint); the
  hidden creation flows stay wired for a clean re-enable.

### Fixed
- **Chat CV attachments no longer lost before the send** — asking AI
  about the open Studio CV could answer "no CV attached": the one-shot
  attach request was consumed into per-surface composer state and then
  wiped by the session transition `openCvChat` performs right after
  (adopting/creating the CV chat session), so the message was sent with
  no attachments. Composer CV references are now store-owned (shared by
  bubble, dock and page, dropped on real session switches) and the
  attach request lands only after the session and surface have settled.
- **CV Studio auto-attaches its open CV in chat** — chatting from the
  Studio now references the CV in view automatically: the composer shows
  it as an attached chip (no click, no "attach it first" replies), and
  removing the chip keeps it out until the Studio CV changes (the
  paperclip picker re-attaches on demand). This replaces the dashed
  "Reference: <title>" suggestion, which read as already-attached while
  attaching nothing — the exact path behind "no CV attached" replies.

### Added
- **CV Studio cards show a first-page preview** — every CV in the
  listing now carries a small thumbnail of its first page on the right
  of the card, printed through the PDF engine, downscaled to
  card-friendly size, and disk-cached per render (any edit, template or
  photo change invalidates it automatically; only the newest thumbnail
  is kept). Without a print engine the card falls back to a quiet
  placeholder — the listing never blocks on it. The whole card is
  clickable (thumbnail included) and opens the CV; the redundant Open
  button is gone and duplicate/delete collapsed into a compact
  segmented pill in the card's top-right corner. Imported source CVs
  no longer render on the page at
  all — they are sources, not studio CVs, and live in the import
  workspace (/profile/import, still reachable via New CV → Import from
  CV and the Profile page), so the list shows exactly one thing: your
  CVs. The page header was rebalanced too — clear action hierarchy
  (quiet Synthesized variants link → outline New cover letter → primary
  New CV) with room to breathe next to the description.
- **Chat can rewrite a CV's bullets (plan 107)** — with a CV attached,
  "update the bullets on this CV" now works end to end: the assistant
  reads the CV's bullet items (`read_cv_items` — ids, current bullets,
  override flags), proposes a `cv_set_bullets` card showing the current
  list against the rewrite, and approving writes the per-CV override in
  the plan-106 canonical shape (revert restores; the open Studio
  refreshes). The Studio's own copilot gets the same op directly
  (`cv_set_bullets` tool), and "how does my CV look?" works from chat —
  `cv_review_visual` ("screenshot the CV") now serves the chat audience
  when a vision model + engine are configured, with honest degradation
  otherwise. The chatbot's system prompt (v12) gains a capability map
  (what it can and explicitly cannot do) and a request-routing playbook:
  ground first with verbatim ids, read before editing, one clarifying
  question on ambiguity, availability honesty, and narrating the review
  contract. Fixed en route: every `cv_*` builder write tool was
  uninvokable (op models required a literal the tool wrapper never
  passed) and the test harness's agent-round mock had drifted from the
  real one.
- **Generate-fill in the bullets editor (plan 106, slice 5)** — an
  AI chip in the editor drafts metric-honest bullets from the item's
  own evidence (the plan-103 dirty-guard applies: unsaved edits ask
  before generating) and loads them as keep/discard chips — nothing is
  written until you confirm the chips and save.
- **Bullet AI action now proposes bullets, not prose (plan 106, slice 4)** —
  the `bullet` writing action targets the achievements layer: it
  returns 1–2 replacement bullets plus the card summary, and Apply no
  longer writes anything directly — it opens the CV Studio bullets
  editor with the suggestions as keep/discard chips against the item's
  current list; saving writes one achievements override for the item.
  **Bullets editor in CV Studio (plan 106, slice 3)** — every
  experience-kind row on the Context tab (jobs, projects, volunteering)
  carries a bullets affordance opening the CV-local bullets editor:
  add/edit/remove/reorder bullets as they render on the CV, with an
  "Edited for this CV" chip when the item is overridden and an explicit
  Reset-to-profile that drops the override. Edits are per-CV override
  patches (profile stays untouched) and flow through the standard
  autosave + undo + preview-refresh path. AI-suggested bullets land in
  the editor as keep/discard chips — never written until you keep them
  (wired to the AI surfaces in the next slices).

### Changed
- **CV bullets unified to one canonical shape (plan 106, slices 1–2)** —
  synth variant payloads now carry `achievements: [{"text": …}]`
  instead of `bullets: ["…"]` end to end: the backend schema, swap,
  snapshot key, renderer and exporter (slice 1), and the frontend type,
  variant editor (string[] UI state de/serialized to entries at the
  API boundary), library and builder previews (slice 2). Every
  dict-or-string tolerance branch is deleted; the synth prompt + mock
  fixture emit the object shape (a string-emitting model now fails
  validation visibly). The generate flow's drafted-bullet overrides are
  unchanged and now share the exact shape everything else uses.
  **Dev/test databases must be recreated after upgrading** — old synth
  rows read back with empty bullets (the stale key is ignored).

## [v0.12.0] - 2026-09-18

### Changed
- **CV item heads restructured** — the organization/school line now
  prints on its own line under the title instead of flowing inline, and
  the period adapts to the column: pinned top-right beside the title
  when the line fits, stacking left-aligned under the title when it
  can't (flex wrap, replacing `float: right`) so dates never overflow
  narrow sidebars nor collide with wrapped institution text; an item
  without a title promotes its org to the head line. The block-size
  estimate charges one extra line per item with an org.
- **Robust contact pieces** — each contact entry (icon + value) renders
  as one atomic unit that never splits across lines; pieces move whole
  to the next line and only wrap internally when they cannot fit the
  column (strict sidebars, oversized links), and printed link addresses
  are no longer truncated with an ellipsis.

### Fixed
- **Generic link labels no longer print** — a contact/item link labeled
  "other" (or any label that merely repeats its kind: website, web,
  site, link, url) now prints the bare address instead of
  "other (example.com)"; meaningful custom labels still prefix the
  address.

### Added
- **Deb packaging regression guard** — the deb build now fails if any
  system-stack library (GL/X/render adjacency, including the
  wayland/EGL family) survives the strip; the Ubuntu-22.04 CI runner
  can never catch the RUNPATH-hijack bug class because its own system
  libs match the bundle, so the guard stands in for it.
- **Create and edit profile items from CV Studio's Context tab (plan 105)** —
  every context group gains a `+` create button and every entry row a
  pencil (edit) plus an external-link ("open in profile") affordance:
  the entity editor modal opens the real workspace editors in place
  (experience — with the right kind preset for projects/volunteer —,
  education, certifications, achievements, and the skills card), saves
  through the profile APIs, then refreshes the context panel and
  preview. Card-backed groups (languages, interests, basics, objective)
  link to their profile section instead. Empty groups offer the create
  action directly. Saves ride the plan-104 live-sync channel with a
  local origin: the panel, preview and staleness state refresh without
  the "Profile changed" toast you'd only want for external (chat)
  mutations — which now also refresh the context source list.
- **Profile entity deep links (plan 105 groundwork)** — a shared
  `lib/entityLinks.ts` map now routes every CV context source to its
  profile home; the experience and education workspaces accept
  `?focus=<id>` (education also `?entity=`) to open the linked entry
  directly in its editor with a one-shot accent highlight, and the
  intake "landed in your profile" links moved onto the same map
  (URLs unchanged). The Studio's new `EntityEditorModal` hosts the real
  workspace editors (experience/education/certification/achievement/
  skills) for in-place editing, with the form→payload builders moved
  next to the editors so the workspace and the modal share one source.
- **Date position per items block** — templates (and the template
  editor) can now set `date_position` on an items block: `auto`
  (default — beside the title when the line fits, stacked under it in
  tight columns), `inline` (always beside the title, never wraps), or
  `stacked` (always its own line between title and organization, the
  classic tight-column resume look). Existing templates are unaffected
  (`auto`); the block-size estimator charges the extra line.
- **Chat → CV Studio live sync** — profile/variant mutations from the
  chatbot now refresh the open Studio without a manual reload: approved
  or reverted HITL cards and finished write-scope tool calls bump a
  builder-link revision counter, and the mounted CV Builder refetches
  its resolved preview, meta and variant rows (debounced, autosave-safe).
- **Variant pinning from chat** — two new chat tools: `variant_list`
  (the variant library with per-CV applicability verdicts) and
  `variant_pin` (star a variant as the default for its item(s) on an
  attached CV — drafts are promoted first per plan-102 star semantics —
  or unpin to restore the profile text). Chat prompt v10 documents the
  flow; the CV document text itself stays read-only to the model.

## [v0.11.3] - 2026-09-18

### Fixed
- **Desktop blank window — root cause found and reproduced** — the CI
  builder's PyInstaller gi hooks drag the Ubuntu-22.04 X11 client family,
  `libepoxy` (GTK/WebKit's GL dispatcher), atk/atspi and the
  rsvg/pixman/fontconfig/text stack into the .deb's `_internal`; the
  executable's RUNPATH let the SYSTEM WebKit resolve its dependencies
  against those old copies first, and WebKitWebProcess aborted at EGL
  init (`Could not create default EGL display: EGL_BAD_PARAMETER`,
  blank window — no page requests at all). The .deb now strips that
  whole adjacency so the system WebKit uses the system GL/X stack
  consistently. Verified by reproducing the blank window with the CI
  bundle on a Mint 22 machine and confirming the strip fixes it; the
  AppImage keeps its self-contained matching stack and is unaffected.

## [v0.11.2] - 2026-09-18

### Fixed
- **Desktop blank window (continued)** — the webkit fallback chain now
  also disables the WebKitGTK bubblewrap sandbox in software mode (the
  sandbox silently kills the WebProcess in some packaged-app layouts:
  blank view, the page never loads, zero requests), and every launch
  logs its render mode at WARNING (mode, soft-fallback state, persisted
  marker, Mesa EGL json presence, session type) so field reports show
  exactly which environment applied.

## [v0.11.1] - 2026-09-18

### Fixed
- **Desktop window on hybrid-GPU Linux (Mint 22 report)** — the webkit
  software fallback now pins both EGL and GLX to Mesa (`__EGL_VENDOR_LIBRARY_FILENAMES`
  / `__GLX_VENDOR_LIBRARY_NAME`) and forces the X11 GDK backend: machines
  whose default glvnd vendor is broken hardware hit `EGL_BAD_PARAMETER`
  even with software rendering requested, and the chain degraded to
  browser mode. The .deb additionally drops the orphaned build-host X11 /
  glib-dependency libraries (libxcb, libXau, libmount, libblkid,
  libselinux, libpcre2, libffi) so the system GTK/WebKit/GL stack is used
  consistently. NOTE for 0.11.0 installs: the in-place 0.11.0 rebuilds
  shared a version string, so `apt` did not upgrade — install 0.11.1
  explicitly.

## [v0.11.0] - 2026-09-18

### Fixed
- **E2E CI stability: two flakes root-caused** — the LangGraph Postgres
  checkpointer now runs on a psycopg connection pool instead of one
  process-lifetime connection that an aborted/cancelled chat turn could
  leave mid-command (poisoning every later turn with "another command
  is already in progress"); stale connections are validated on checkout
  and recycled. Match insights upsert race-free (`INSERT … ON CONFLICT
  DO NOTHING` on Postgres and SQLite) — concurrent dashboard/feed
  scoring of the same job no longer 500s one request per page. A failed
  chat turn now logs its traceback server-side.

### Changed
- **README restructure** — the developer/feature detail that had grown in
  "Features", "Structured by design" and the "Recently shipped" rollout wave
  deduplicated into a compact feature tour plus a new
  [docs/features.md](docs/features.md) feature catalog ("everything, as
  built", the family-standard pattern); seed-count and version drift
  (0.7.x → 0.10.x) fixed in Scope.

### Removed
- **Context panel "Improve with AI" wand button** — the per-item bullet
  improve action (the only caller of the `bullet` AI action) superseded
  by the AI toolbar's actions and the variant editor's generate;
  frontend wiring removed (backend `aiAction` contract kept for API
  compatibility).

### Added
- **Variant cards in the smoke suite + chat hygiene (plan 101.4)** —
  E2E goldens now cover the full variant-card lifecycle (resolved
  labels, before-only source preview, approve drafts into the Synth
  Library, no revert row) and the education edit golden (card → preview
  highlight → approve → workspace finished date → revert restores). The
  chat grounding prompt stops the agent from calling autopilot-goal or
  job-comparison tools as if they were grounding digests (CHAT prompt
  v9); the preview endpoint contract now documents the stacked
  cv_synth source shape.
- **Education/certification/achievement previews render their item card
  (plan 101.3)** — the proposal preview modal renders a per-kind
  snapshot card (labelled rows, focus-subjects chips, month-year dates,
  the changed prose span highlighted) instead of a raw key/value dump;
  variant cards get their before-only "What the variant drafts from"
  preview with one source card per ref (deleted sources degrade to
  label-only rows) and never show a revert row — variants retract via
  the Synth Library.
- **Chat variant cards preview their sources (plan 101.2)** — a variant
  card's "Preview" now shows exactly what the variant will draft from:
  the user's current snapshot of every referenced source item
  (experience/education/…) plus the target posting, before-only with the
  unchanged "drafts variant rows on approve" semantics. Cards from before
  plan 101 (and all-deleted source sets) keep hiding the button.
- **Chat variant cards name their sources (plan 101.1)** — a
  "create a new variant …" card now shows one human-readable chip per
  referenced source item ("Siemens internship", "BSc Informatics")
  instead of a raw `experience:<uuid>` row; the card title abbreviates to
  the primary label ("Add CV variants · Sample Internship (+2) · restyle"),
  unreadable/deleted source refs degrade to "Unknown item", and a
  posting-aimed variant names the posting's public reference. The chat
  narration follows the same resolution (no UUIDs in the answer prose).
  Education entries gained a deterministic chat flow in mock/E2E runs:
  "finish my education entry" closes an open-ended education item
  (card → diff → approve → revert).
- **Variant editor: AI generate-fill + slot browser (plan 103)** — the
  variant editor is now the single variant surface: an "AI generate"
  toolbar (action chips, target language for translate, advanced
  tone/length) drafts a variant and fills the payload in-form (with a
  dirty-guard confirm; the generated draft row is adopted by the form),
  "Save & use this" promotes it via the star path in one action, and
  ⌐/¬ chevrons (+ compare list) flip through the slot's existing rows
  with an "on the CV now vs. in this form" preview snippet and
  optimistic landing for saved drafts. Context-`+` opens the editor
  pre-bound to the item.

### Changed
- **Variant editor: custom instruction (plan 103 follow-up)** — the AI
  generate toolbar gains a free-text "Custom instruction" field
  (backend `CvSynthItemGenerate.instruction`, threaded through the library
  generate flow, the editor's generate-fill and the chat
  `cv_synth_generate` tool); the grounding contract is restated in the
  system prompt so steering never lifts the evidence allowlist.
- **Variant approval overhaul (plan 102)** — approval = activation:
  starring a draft variant in the Context panel now activates it in one
  action (the `pin inactive` dead-end state is retired), chat-generated
  variants go live immediately (the request itself is the approval;
  `activate=false` keeps drafts), stale variants gain a **Reset**
  button, and manually editing a variant re-grounds it (clears the
  stale badge unless the source drifts afterwards). The Context panel
  no longer shows `variant`/`draft` chips or inline Activate buttons —
  the library remains the variant workspace.

### Fixed
- **Variant generation 500 on length mismatch**: the editor sent the
  CV-style length enum (`standard`) but the synthetizer's
  `compose_system` indexes `LENGTHS` by renderer keys — the lookup is
  now guarded and the editor maps concise/standard/detailed →
  short/medium/long (same mapping the one-shot pipeline uses).
- **Variant editor generate toolbar**: the tone field is now a dropdown
  of the backend-supported tones (none/professional/warm/concise/
  confident) instead of a free-text input, and an unknown tone string
  no longer crashes generation (the prompt falls back to a guarded
  register line) — the free-text steering path is the Custom
  instruction field only.
- **E2E smoke environment**: `scripts/run-e2e.sh` now opts the mock AI
  provider in explicitly (`MOCK_AI=1` — the opt-in knob requirement of
  plan 99.1), disables the gateway's per-user AI rate limiter
  (`AI_RATE_LIMIT=0` — the suite makes far more mock calls than the
  30/min default, and the last AI-heavy specs used to 429 with
  "retry in 23s"), and recreates the scratch database each run so a
  stale seeded mock provider cannot bypass mock-fixture registration
  (generic "mock_answer" turns otherwise).

### Added
- **Rendered before/after preview + one-click revert on proposal cards**  (plan 99.6): entity-edit cards now carry a Preview action (hidden for
  `user_skill` / `profile_section` / `cv_synth` and on 404) — the modal
  renders the real item card before/after side-by-side (SegmentedTabs
  toggle on narrow viewports; creates after-only, deletes before-only
  with the destructive tint) with the changed sentence highlights from
  the anchored edits; payloads lazy-fetch from the new snapshot
  endpoint through a transient store cache. Approved cards carry an
  armed two-step Revert ("Confirm revert") that inverse-applies
  server-side and flips the card to the terminal `reverted` status;
  a 409 (target edited after the apply) shows "changed since applied"
  copy. The pipeline drop reasons (`unread_target`, `anchor_mismatch`,
  `anchor_ambiguous`, `conflicting_edit`, `duplicate_target`) and the
  99.3 pipeline `profile_op_errors` render as friendly one-liners
  under the card stack.
- **Proposal previews + one-click revert** (plan 99.4): entity-edit
  cards now persist full before/after snapshots (KIND_SPECS-shaped,
  unchanged children included, delete payloads carry the full snapshot
  for recreate), served lazily by the new owner-scoped
  `GET /me/profile-proposals/{id}/preview` endpoint (`{before, after,
  edits}`; 404 for kinds without snapshots — `user_skill`,
  `profile_section`, `cv_synth`, and pre-99 rows). Card diffs gain
  structured collection rows (skills keep label/role/level,
  achievements text/metric, links url) plus one legible per-edit
  summary row in order ("replaces '…'", "adds skill: docker
  (secondary)"); scalar strings render exactly as before. Approved
  cards gain `POST /me/profile-proposals/{id}/revert`: update restores
  `base_snapshot`, delete recreates entity + children from the payload
  snapshot, create deletes the created row — all through the same
  services — blocked with 409 when the target moved after the apply,
  terminal `reverted` status (migration 0037 widens the status CHECK).
- **Self-healing profile-edit pipeline before the answer streams**
  (plan 99.3): edit-intent turns now draft the ops in one non-streaming
  gateway call (`chat_ops` task, audited `ops_draft`/`ops_repair`),
  validate + resolve them against the grounding/anchors server-side,
  and — on a quoted-anchor or ungrounded failure — run ONE repair round
  with the verbatim error feedback before the visible reply streams.
  Validated ops ride the turn state (the streamed reply's own ops are
  ignored on pipeline turns); still-failing ops surface as a visible
  "skipped" note with per-reason telemetry (`profile_op_outcomes`).
  The read-before-edit nudge is now a deterministic notice carried on
  every agent round of edit turns. Chat prompt v8.
- **Anchored profile edits — silent overwrites are now structurally
  impossible** (plan 99.2): update ops carry exact-anchor `text_edits`
  (`replace` must match the current text exactly once — never "replace
  first" — `append`/`prepend` only add) and granular
  `collection_edits` (skills/achievements/links add/remove, removes
  matched by stable child id from the read result). Edits resolve
  sequentially server-side into the reviewed payload; full-replacement
  of child collections inside an update payload is retired
  (`conflicting_edit`) and a second op on the same item is dropped
  (`duplicate_target`) — one coherent card per entity. Card diffs now
  render long-text changes losslessly (cap 200 → 2000 chars), so an
  anchored edit inside a long description can no longer vanish from
  the diff. Chat prompt v7.
- **Read-before-edit gate for chat profile edits** (plan 99.1): the
  assistant must open an item's full content (`read_profile_item` /
  `read_profile_section` tools — digests truncate long text at 140
  chars) before proposing an update or delete to it; ops on unread
  targets are discarded server-side with a visible "skipped" note
  instead of silently overwriting content the model never saw. Reads
  persist per entity in the session digest cache (freshness-signed),
  so follow-up turns editing the same unchanged item stay grounded.
  Degraded providers (no tool support) no longer emit edit cards at
  all — a deliberate safety regression. Chat prompt bumped to v6.
- **Chat engine groundwork for the chat-turn graph migration**
  (family ADR-0016, plan 98 — pre-release cutover, no legacy window):
  the gateway gains `ainvoke_agent` (native tool rounds through the
  same audited/budgeted funnel, JSON mode off for tool calling,
  scriptable mock for tests/E2E); registry tools can be exported as
  bind specs for the main chat (surface-owned families excluded);
  desktop checkpoint retention gets a boot-time prune
  (`CHECKPOINT_TTL_DAYS`, default 14).
- **HITL capability rows in the chat tools catalog** (family
  ADR-0015): the "Tools the assistant can use" dialog now also lists
  what the assistant can *propose* — a "Propose profile edits"
  capability card badged "HITL action" explains that chat edits
  always arrive as review cards you approve first. Registry tool rows
  gain `kind` (`tool` | `capability`) and `hitl` fields; capabilities
  are opt-in via `GET /ai/tools?include_capabilities=true` and can
  never execute (`run_tool` rejects them; MCP/admin surfaces stay
  callable-only).
- **Profile-edit proposals now notify** (family ADR-0015 fanout):
  when a chat turn creates proposal cards, an in-app/desktop
  notification ("Profile edit proposal waiting for review", linking
  to `/profile`) is emitted through the notification funnel so
  proposals survive a closed chat window. New mutable
  `profile_proposal` notification kind (seeded).

### Changed
- **The chat stream now speaks only the family event vocabulary**
  (plan 98 SSE convergence): the duplicate legacy `status`/`done`/
  `error` events are gone — `flow_started` (now carrying
  `stage`/`found`), `flow_finished` and `flow_failed` are the single
  turn lifecycle, alongside `delta`, `tool_call`, `meta`, `proposal`
  and the surface terminals (`builder_state`, `preview`,
  `interview_state`). One event name per concept family-wide; smaller
  payloads per turn.
- **Chat checkpoints now have server-side retention** (family ADR-0016,
  plan 98 Phase 4): a daily `system_checkpoint_prune` schedule runs the
  `checkpoint_prune` job, deleting LangGraph checkpoint threads older
  than `CHECKPOINT_TTL_DAYS` (14) plus their orphaned blobs/writes —
  the desktop already prunes its SQLite file at boot. A new migration
  (0036) widens the schedules CHECK constraints for the new slot.
- **The chat turn now grounds itself with native tool rounds** (family
  ADR-0016, plan 98 Phase 3): before writing its reply, the assistant
  can call registry tools itself — digest tools (experience, skills,
  education, profile) are pulled on demand and their results persist
  into the session cache, so edit proposals ground on real ids without
  pre-running every digest on every turn. Budgets keep turns honest:
  at most 3 agent rounds and 6 executed tools per turn (over-budget
  calls drop with a persisted reason), and a provider that cannot call
  tools degrades to the previous digest-stuffing behavior (worst case
  = parity). Tool cards stream into the transcript as they execute;
  the deterministic detections (catalog search, posting refs,
  notifications, web prefetch) stay code-owned.
- **The main chat turn now runs as a checkpointed graph** (family
  ADR-0016, plan 98 Phase 2 — pre-release cutover, the single-reply
  loop is gone): the turn is `retrieve → synth → hitl → finalize`
  (`app/ai/graphs/chat_turn.py`) with the same SSE contract, byte for
  byte — status/flow events, tool cards, deltas, proposal cards and
  notifications all behave identically, and an aborted stream still
  persists its partial reply. Per-session single-flight guards
  concurrent turns; each turn checkpoints under
  `chat:{session}:{message}` (foundation for resume/branching).
  Surface-owned flows (CV copilot, interview practice) are unchanged.
- **One chat surface at a time: the chat page now takes over** —
  opening `/chat` closes an expanded floating bubble (it stays closed
  after leaving the page) and the docked side panel no longer renders
  beside the page; the conversation that was open in either surface
  opens on the page (the shared active session survives), and leaving
  the page restores the dock with that same conversation (the
  interview hand-off is unchanged). Choosing the popup shape from the
  view switcher is now an explicit open gesture — the floating window
  expands immediately instead of leaving only the launcher bubble.
- **Experience editor: bullets are now a first-class section** —
  the structured highlights move up beside the description as
  reorderable "Bullets" (↑/↓) with roomier inputs and an optional
  schema-backed metric per bullet (kind / value / unit, rendered as
  real bullets on CVs and kept by ATS exports). The free-text
  description stays prose on purpose — the CV pipeline formats it.
- **Redesigned the experience editor and kept the list in view**:
  opening an entry now scrolls the rail so the selected card stays
  visible; the form itself gets a next-gen layout — icon kind pills,
  an inline display-style title and organization line, a grouped
  "period & setup" panel (dates, ongoing toggle, hours, on-site
  policy), sectioned labels and skill rows as individual elevated
  chips. All controls and behavior are unchanged. The form body now
  uses the pane's width (max-w-4xl) and on wide workspaces the
  description editor and bullets sit side-by-side (container query —
  chat-dock safe); the duplicated skills header is gone. The period
  panel stacks into two labeled columns (ongoing/start/end and
  hours/on-site) and the sticky Cancel/Save footer reserves the
  bottom-right corner so the floating chat bubble no longer covers
  the Save button.
- **Experience workspace shows all entries in a full-width grid when
  no entry is open**: closing the editor (or just landing on the
  page) lays the entry cards out in a responsive multi-column grid
  across the whole workspace instead of a narrow rail beside an
  empty "Nothing selected" pane — opening an entry brings back the
  master-detail split with the editor.

- **Experience (and Education) workspaces give the item list more
  room**: the master-detail split now uses the wide rail (up to
  ~400px for navigating existing entries) instead of the default
  260–340px — the editor form stays capped and centered, so the
  reclaimed space comes out of its dead whitespace.
- **Experience workspace: skills move to their own tab and entry
  cards shrink**: the skill-level estimates panel (with the
  auto-apply status) now lives under a dedicated Entries / Skills
  tab switch instead of sitting above the entry list, and cards are
  more compact — tighter padding, smaller icon, descriptions clamped
  to one line (full text on hover) and at most three skill chips.

- **Experience workspace: skills move to their own tab and entry
  cards shrink**: the skill-level estimates panel (with the
  auto-apply status) now lives under a dedicated Entries / Skills
  tab switch instead of sitting above the entry list, and cards are
  more compact — tighter padding, smaller icon, descriptions clamped
  to one line (full text on hover) and at most three skill chips.

- **The mock AI provider is now opt-in** (was auto-provisioned in
  dev): set `MOCK_AI=1` or start the dev group with
  `./scripts/run-dev.sh --mock-ai` to enable the built-in offline mock.
  Without it, dev AI endpoints answer 503 until a real provider is
  configured in Settings → AI Configuration — and already-seeded mock
  rows in older dev databases are invisible to task resolution.
  Production still blocks the mock provider entirely.
- **Rankings and job page show all scores together**: the score ring
  (now labeled "match" — the blended 0.6·fit + 0.4·AI score) sits
  beside a compact fit / AI / your-score stat cluster on both the
  Rankings rows and the job detail score card, with the sidebar logo
  navigating back to the dashboard. A shared "How scores work" ⓘ
  popover (Rankings header + job page score card) explains the score
  layers, the blend and the neutral-dimension rule.

### Removed
- **The non-streaming chat API is gone** (plan 98 cleanup — nothing
  consumed it): `POST /chat/sessions/{id}/messages`, `/chat/messages/{id}/edit`
  and `/chat/messages/{id}/regenerate` no longer accept `?stream=false`
  or return JSON message pairs — they are SSE-only (the web app always
  streamed). The dead sync machinery behind it is deleted
  (`ChatService.send_message`/`finish_turn` + builder/interview sync
  turn drains, `chatbot.chat_reply`); aborted or failing turns surface
  in-stream (`flow_failed`/`error` events) instead of HTTP errors.

## [v0.10.0] - 2026-09-16

### Changed
- **CV Studio panes follow the available width too**: the CV builder and
  template editor panes now switch their layout by the space they actually
  get (container query) instead of the window width — beside the chat
  sidepanel the builder swaps to its List/Editor-style pane switcher and
  the template editor keeps a sane settings/preview split instead of
  crushing the panes.
- **Catalog → Profile-style layout (plan 96)**: the job-catalog tree now
  uses the same two-pane section shell as the Profile page — job families
  sit in a left rail (with job counts) beside search and results, instead
  of a full-width list pushing the jobs down. Sub-families drill in as
  chips, and the whole page adapts to the space it actually gets: chips
  when narrow or beside the chat sidepanel, rail when wide.

### Fixed
- **Fixed the UI breaking on narrow windows with the chat sidepanel
  open** (plan 95): the Settings/Profile section rails no longer
  truncate their labels ("AI C…", "Ba…") when the sidepanel squeezes
  the page — the rails now respond to the space they actually get
  (assistant-ui `SettingsShell` container-query modes: wrapping chip
  row when narrow, classic rail when wide). The chat sidepanel itself
  never pushes the page below a usable width on wide screens, and on
  small screens it opens as a full-screen chat instead of collapsing
  the page to zero width. The Experience/Education/Interview
  workspaces switch their list/editor panes by available width too,
  so the editor is no longer crushed beside the sidepanel.
- **Fixed** the Linux `.deb` failing to start on newer distros (Ubuntu
  24.04 / Mint 22+): the package accidentally shipped the build host's
  GLib/GTK stack, which hijacked the system's newer libraries at startup
  ("undefined symbol: g_once_init_enter_pointer" /
  "webkit_get_major_version"). The `.deb` now uses the system GTK/WebKit
  libraries it always declared as dependencies; the AppImage keeps its
  self-contained stack.
- **Fixed** the CV polish review crashing when the PDF engine printed the
  document but its page count came back unreadable — the review now falls
  back to lint-only facts (the count stays `unverified`) instead of erroring
  the run.

## [v0.9.0] - 2026-09-16

### Added
- **Auto-generated chat titles (plan 93)**: a chat session's title is now
  generated from your first message by a small fast AI task (assignable in
  Settings → AI Configuration); when no AI model is configured it falls
  back to the first line of your message — sessions never sit untitled as
  "New chat".
- **Fresh chat on open (plan 93)**: opening the chat page, bubble or dock
  now starts a clean composer immediately — sessions are only created when
  you actually send the first message, and empty sessions no longer appear
  in the history list.
- **Sunken workspace panes (plan 90)**: the builder's inspector is now a
  slightly darker tray, so the section cards, context groups and inputs
  inside it visibly float instead of blending into the pane — a
  three-step elevation ladder (tray → surface → raised) using the
  existing theme tokens, in both light and dark themes.
- **Context panel at a glance (plan 89)**: the builder's Context tab now
  opens with a coverage summary ("N / M items on the CV"), every group
  header shows how many of its items are included (accent-highlighted
  when the whole group is on), and empty groups say "Nothing recorded
  yet" without needing to expand. The include-all header control is now
  a proper tri-state checkbox.
- **Segmented inspector tabs (plan 88)**: the builder's inspector
  switcher is now a pill-style segmented control with icons and a
  sliding thumb (arrow keys work, reduced-motion safe) instead of a
  dropdown menu — all three tabs (Context, Design, Sections) are visible
  at a glance and one click away.
- **Lint report in the ATS chip (plan 87)**: clicking the ATS score chip
  in the builder toolbar now opens the full lint report (score,
  pass/warn/fail summary and every check) as a popover — the Lint tab is
  gone and the inspector is down to three workspaces: Context, Design,
  Sections.
- **AI actions moved to the toolbar (plan 86)**: the builder's AI tab is
  gone — the one-click writing actions (Improve summary, Tighten text,
  Find gaps, Translate, Tailor to posting) now sit next to the "Ask AI"
  button as an always-reachable menu, with tone/length presets beside
  them. Cover letters get a dedicated "Draft with AI" toolbar button.
  The copilot's critique card now appears over the preview it critiques
  (dismissible), and Duplicate CV/letter moved into the Versions panel.
  The inspector is down to four tabs: Context, Design, Sections, Lint.
- **One Design tab (plan 85)**: the CV builder inspector's split
  Design/Template tabs are merged into a single Design tab — template
  choice (picker, Browse…, Customize), style tokens + page size, profile
  photo and the printed-copy check now live on one scroll with a pinned
  Apply/Reset bar, instead of two backwards-named tabs.
- **Sections panel redesign (plan 84)**: CV Studio section cards are
  rebuilt — every card shows a config summary line ("Work Experience ·
  List · Jan 2025 · max 10") at a glance, titles no longer truncate
  (all section titles rename in place now), and the actions moved from
  hover-only buttons to an always-visible menu (move / duplicate /
  remove) with keyboard reorder on the drag handle (↑/↓). Sidebar
  template groups got real headers with a compact "+" per area instead
  of the triplicated full-width "Add section" buttons.
- **Hide sections without deleting (plan 84)**: each section card has an
  eye toggle — hidden sections stay configured in the builder but drop
  out of the preview, the printed PDF and every export (PDF/DOCX/MD/ATS
  text), and the lint stays consistent with what is rendered. Toggle it
  back on anytime; duplicates always start visible.
- **The CV copilot can see templates now (plan 83)**: ask it to "switch to
  a more modern template" and it renders first-page previews of the
  current template plus up to three candidates and judges them visually
  (density, whitespace, typography) — capability-detected, degrading to
  metadata-only advice without the print engine. The chat shows you the
  same previews as clickable thumbnails during the turn and keeps them in
  the message history. Previews are served from a content-hash cache
  (`GET /cv/templates/{id}/preview.png`, 503 without the engine).
- **Chat-proposed CV variants (plan 82A)**: ask the chatbot to "generate
  variants for my projects" and it proposes a single review card (refs
  copied verbatim from your profile digests, at most 10 items) — approving
  it creates the synthesized variants **active** in the CV Synth Library
  (the card approval is the review; the previous variant in the slot
  retires). Up to 5 items draft inline, more ride the background queue
  (the completion notification announces the active variants). Card
  resolution is terminal before drafting: a failure leaves an approved
  card with the error recorded, never a retryable card that would
  duplicate drafts.
- **Chat proposals can link skills, achievements and links (plan 82B)**:
  experience-item suggestions now understand the child collections the
  forms already support — skill links (keys copied from your skills
  digest), achievements and links — with replace semantics on updates
  documented for the model.
- **Links on work experience & projects**: experience items now support
  up to 10 attachable links (label + URL + kind: GitHub / LinkedIn /
  demo / web) with scheme validation — the experience editor gains a
  links repeater (and no longer silently wipes links that arrived via
  chat proposals or intake when you edit an item), the CV template
  editor gains a per-items-block "Show links" toggle (off by default —
  when on, up to three links render print-first under the item), and
  proposal cards show links as clean URL chips.
- **Web tools for the AI chat (plan 80)**: pasted links are now read and
  reasoned about. A GitHub URL produces a repo lookup (metadata + README
  via the GitHub REST API), any other link is fetched, reduced to readable
  text and summarized — JS-heavy pages fall back to the plain fetch when
  no Chromium engine is installed. A user-hosted SearXNG instance can now
  back live web search: set the URL (plus optional GitHub API token) under
  Settings → AI ("Web tools" card via `PUT /ai/web`); searches degrade
  gracefully when it is unconfigured or unreachable. All fetched content
  is SSRF-guarded, size-capped and treated strictly as reference data.
- **CV Studio power pack, slice 1 — template capabilities (plan 79.1)**:
  grouped skills now render as true category sections with subheadings
  (the "Grouped" option previously fell back to plain chips), sections can
  carry small heading icons (per-block `icon` override or `""` to clear,
  toggled by a new `show_heading_icons` token), the profile photo gains an
  "arch" shape, the header name can split into two tones
  (`name_style: "accent_surname"`, with a readable lighter tint inside
  accent bands), the main/dashboard column can flow in two newspaper
  columns (`main_columns` / `sidebar_columns`), and two bundled OFL font
  stacks ("Embedded Sans" = Inter, "Embedded Serif" = Source Serif 4) ship
  inline — zero network, license text included. All capabilities are
  additive and default-stable: existing templates render byte-identically,
  and the designer/copilot vocabulary learned every new token.
- **Template gallery gets filters, comparison and your-data previews**
  (plan 79.2): filter the picker by two-column/single layout, one-page
  budget or ATS safety; select up to two templates and open a
  side-by-side comparison rendered against **your own CV's resolved
  data** (with a fits/over-budget page chip per side — an empty profile
  gracefully falls back to the deterministic sample); a new
  `set_block_area` builder op swaps any section between the columns
  (single-column templates ignore it), exposed to the copilot as well;
  previews of photo-enabled templates pair with a neutral placeholder
  portrait, and bank previews now sell the photo layout.
- **One-click matching cover letters from the builder** (plan 79.3):
  CVs with an attached posting get a "Matching cover letter" action in the
  Download menu — it creates the letter document bound to that posting,
  inheriting the CV's template (accent/typography/design tokens carry
  over automatically through the shared pipeline) plus its context
  selection and language, and lands you in the letter editor. Hidden for
  letters themselves and when no posting is attached.
- **Power pack slice 4 — print extras** (plan 79.4): templates can switch
  on a running page-2+ footer (`running_footer: "name" | "numbers"`)
  rendered through `@page` margin boxes — real `p/N` page numbers reach
  the printed PDF (engine-verified; degraded engines simply omit them);
  a new `qr` block kind renders the first matching profile link
  (web/GitHub/LinkedIn, scheme-allowlisted) as an inline SVG QR panel —
  deterministic, CSP-safe, hidden when no link matches; default section
  titles localize per CV language (English/Greek/German built in,
  English fallback); admins get `GET /cv/templates/stats` with anonymous
  export totals per template derived from the immutable version rows
  (no new telemetry pipeline). The Coral Banner template adopts the new
  arch photo shape and the token editor drops a duplicated control.
- **Power pack slice 5 — bank refresh + version history (plan 79.5)**:
  the template bank adopts the new capabilities — "Navy Sidebar" gains
  heading glyphs and a running "Name — CV" footer (suppressed on page 1
  where the header already carries it), "Teal Sidebar" gains glyphs,
  "Modern Two-Column" groups skills by category, "Coral Banner" upgrades
  to the arch photo with a two-tone accent surname, and "Charcoal &
  Amber" adds heading glyphs, the accent surname and a scannable QR
  panel for the portfolio link in its sidebar. Every refreshed layout
  lints clean and prints within its page budget (engine-verified). The
  template editor also gains a **Version history** panel: all version
  rows of a template key plus a deterministic v(n−1)→v(n) diff (token
  path changes and block add/remove/props) via new
  `GET /cv/templates/{id}/versions` and `/diff` endpoints — no images,
  so it works identically with or without a PDF engine.
- **New CV templates inspired by magazine-style layouts**: "Coral Banner"
  (warm coral header band with a circular photo, soft gray sidebar with
  profile, skill bars and CEFR languages) and "Charcoal & Amber" (dark
  charcoal sidebar holding the photo, contact, education and skill bars
  with amber accents over a timeline main column). Both are full
  two-column sidebar templates using areas, timeline items, icons and
  the new `header_style: "band"` token (also editable in the Design
  Token editor and shipped as the two new `coral_banner` / `amber_charcoal`
  themes). Bank previews pair with any profile photo the user attaches.
- **One chat: CVs as references, builder on demand** (plan 78): the
  chatbot is one surface everywhere. Attach a CV (or cover letter) to any
  message — the composer suggests the CV you have open in Studio, the
  paperclip popover attaches any document — and the answer is grounded in
  it (plain-text reference of the current state; reading never creates
  versions). Reply and user message carry deep-link chips. Asking for an
  actual edit ("rewrite the summary") while a CV is attached hands that
  single turn to the builder copilot — in the same session, no re-routing;
  questions stay normal chat. Attachments are per-message (max 2),
  validated for ownership; follow-ups without their own attachment keep
  the grounding as an "attached earlier" reference; edit/regenerate
  preserve attachments. CV Studio's "Ask AI" now opens the normal chat
  with the CV attached instead of silently converting the session into a
  copilot (existing bound sessions keep working). Fixes along the way:
  a failed builder operation could expire shared ORM instances mid-turn
  (greenlet crash) and roll back the just-typed user message — both now
  handled (instances revived, the user message is durable before any
  operation runs).
- **Profile editing through the chatbot, reviewed on HITL cards**: ask the
  chatbot to add a project, end an internship, set a language level or
  delete a certification and the change lands as a proposal card right in
  the chat that you approve or reject — never auto-applied. Each card
  shows a field-level before/after diff (long texts as a proper line
  diff), destructive changes require an explicit confirm step, and
  resolution is idempotent. Approving re-validates against current data:
  changed data turns the card into a "changed since proposed" review
  state, deleted data expires it. Applying goes through the same services
  the profile forms use, so validation rules are identical everywhere.
  The chatbot grounds every edit in read-only profile digests (real ids
  only — nothing is invented), ambiguous requests get a clarifying
  question instead of a proposal, at most 5 cards per turn (excess ops
  are reported as dropped), and cards survive session deletion with a
  14-day TTL, swept daily by the scheduler. Cards render on every chat
  surface (bubble, docked, page), stay in sync across them, and the
  Profile sidebar entry shows a count badge while cards await review
  (`GET /me/profile-proposals` + approve/reject/dismiss endpoints).
- **Your name is editable — and imported**: the Basics card gains a
  "Full name" field (it mirrors the account display name that the CV
  header shows), and CV intake applies the extracted name like every
  other basics field — a name that differs from the account's shows up
  on the review screen as a Keep-or-Replace conflict.
- **Activate from the edit form**: editing a draft variant (library or
  builder) shows a "Use it" activation row in the form itself, next to
  the tree's inline Activate.
- **Kept polish variants activate themselves**: when the agentic polish
  loop's review keeps a grounded variant, its library row becomes
  active and is starred on the CV immediately (it was already accepted
  into the CV) — no orphan drafts from successful polish runs.
- **Draft variants are visible in the builder's context tree**: CV Studio
  now nests draft variants (amber "draft" badge) under their source
  items right next to the active ones, with an inline Activate button —
  previously only active variants appeared, so variants generated by AI
  runs or the library seemed to vanish from the builder. Archived
  variants stay out of the tree; the library remains the full list.
- **Linked items surface as chips in the variant library**: the synth
  library (`/cv/synth`) resolves each variant's source refs into real
  item names — accent chips on the group header and a "Based on" chip
  row on every variant (falling back to the source-type + id slice when
  an item no longer resolves, e.g. orphaned sources). The VariantEditor
  shows the same resolution: readonly named chips in edit mode, and
  removable selected-item chips above the picker when creating
  (removing a chip also unchecks the item).
- **AI-generated CVs name themselves**: the section planner now also
  proposes the CV's title — the target role when one exists ("CV — ICU
  Nurse"), otherwise the profile's strongest angle — shown in the CV
  Studio list and the builder; sanitized through the rich-text gate with
  the deterministic "CV — {posting}" fallback when planning fails.
- **Rich text in the variant editor**: writing or editing a synthesized
  variant's description now uses the visual editor (bold, italic, links)
  instead of a plain textarea.
- **Rich text in CV prose (bold, italic, links)**: experience, education,
  project descriptions, achievements, summaries and custom-text sections
  now support a bounded markdown subset — `**bold**`, `*italic*`,
  `[text](url)` and line breaks — rendered consistently in the HTML/PDF
  preview, DOCX and markdown exports (ATS text strips the markup). The
  visual editor (library `RichTextEditor`, toolbar limited to the
  supported subset) replaces the plain textareas in the experience and
  education workspaces, cover-letter paragraphs and the builder's
  custom-text sections. A single normalization gate strips everything
  else (headings, lists, images, raw HTML, unsafe links) from every
  write path — user input and AI output alike — and the AI drafter is
  instructed to use the subset sparingly for emphasis and links.
- **AI runs panel surfaces run warnings**: generation/polish runs show a
  warning badge and, expanded, the full warnings list (plan fallbacks,
  skipped variant groundings, sections that kept profile text, rejected
  polish ops context) — previously this data was persisted but invisible.
- **CV import now fills your basic profile details**: headline, email,
  phone, city, country, birth year (only when explicitly stated) and
  links are extracted alongside everything else and land field by
  field on the review screen. Where your profile already holds a
  different value, the row shows your current value with an explicit
  Keep / Replace choice — nothing is overwritten silently; matching
  values and already-saved links are marked as such, and the import
  report lists what was kept.
- **Hidden in-development pages with a developer menu**: Postings,
  Autopilot, Interviews and Growth are removed from the sidebar
  (deep links still work). A hidden trigger at the bottom of the
  sidebar unlocks dev mode — 5 taps within 2 seconds — and its popover
  lists the in-progress pages for one-click access; "Lock again"
  hides them once more. The unlock persists across reloads via
  `localStorage`.

### Changed
- **The chat continues after you resolve your cards**: once the last
  pending proposal card of a session is approved or rejected, the
  assistant follows up automatically — from an honest, visible synthetic
  user message ("(resolved card: … — approved)") run through the normal
  chat turn, so the transcript explains itself and the chatbot can
  confirm what changed. Guards: at most one follow-up per resolution
  burst (never chains), fires only for the session you are actually
  looking at, and cross-surface double-sends are impossible by a
  store-level guard.
- **Cleaner HITL create cards**: proposal cards for new items (e.g. "Add
  project X" turns) now render a proper item summary instead of a
  before→after diff — empty fields ("Organization —", "End date —") are
  skipped, fields render as tidy label/value rows and long descriptions
  as plain prose instead of red/green line diffs. Update and delete
  cards keep the true field diff (library `chat-hitl` create-mode).
- **Richer bank templates (spec version 3)**: "Modern Two-Column",
  "Compact One-Page", "Academic" and "Student First" gain certifications
  sections, skill levels and CEFR language bands; "Navy Sidebar" and
  "Teal Sidebar" upgrade to explicit `area` marks with photo support,
  skill bars and certifications in the sidebar. The renderer now keeps
  header text, contact links and skill bars legible inside dark sidebar
  columns (currentColor contrast) and wraps long contact links within
  the narrow column instead of overflowing onto the page.
- **Robustness-first polish runs**: the generation loop's safety cap
  rises from 3 to 6 review→fix rounds (pending judgements still extend
  by one) and each round may apply up to 8 builder ops instead of 6 —
  the loop keeps densifying/compacting/redesigning until the CV fits
  its budget, so token spend stops being the limiting criterion. A
  two-round stale-stop ends the loop early only when the applier keeps
  rejecting everything (recorded in the trace), so dead sub-runs don't
  burn six reviews for nothing.
- **Generation densifies before it cuts**: the polish loop's fix
  vocabulary now densifies first — over-budget or cramped builds get an
  `update_design` compacting pass (use the design tokens: base size,
  spacing scale, section/item gaps, sidebar width) before any content
  is trimmed, and the reviewer is taught the size vocabulary and bounds.
  Sidebar content that clips argues for a wider sidebar or tighter type
  — the section never gets dropped to save space; a run can therefore
  land compact and information-rich without losing content.
- **Generations auto-star the variants they used**: when an AI generation
  grounds synthesized variants into the draft (gap variants), finalize
  activates those rows and stars them on the new CV (`synth_starred`
  shows in the run trace) — regenerations and "prefer" tailoring now
  reuse the same variant text instead of re-grounding from raw profile
  text. The polish loop's kept variants are starred the same way.
- **Variants are starred per item — the global "prefer synthesized" toggle is
  gone.** A variant now applies to a CV exactly when it is starred
  (`context.synth_pins`) as the default for that item, and starred by
  its item being selected in the context tree. Nothing else gates it,
  so earlier active-but-unapplied variants work everywhere. Applies
  across builder, generate flow and the copilot (the `cv_synth_enable`
  tool and `synth_mode` are removed; dead/foreign-language pins fall
  through to verbatim profile text; the lint hint now suggests starring
  an unpinned variant instead of enabling a mode).
- **Typographic fit vocabulary widens**: the reviewer is taught
  `line_height` (1.0–2.0) and told font_stack + heading tokens are look
  levers, not fit levers — the densification vocabulary stays explicit
  and bounded.
- **Sidebar regrouped into clearer sections**: Dashboard stands alone,
  then *Job hunt* (Chat, Catalog, Rankings, Postings, Autopilot,
  Interviews), *Prepare* (Growth, CV Studio), and *Account* (Profile,
  Settings) — moving Growth and CV Studio out of the undifferentiated
  job-hunt block.
- **Generation lands in the builder automatically**: when an AI
  generation finishes, the flow opens the builder directly (with the
  copilot docked) instead of showing an intermediate "Open the builder"
  step — including runs that applied or proposed synthesized variants;
  the variant info surfaces in the builder and the synth library.
- **AI template redesign is now area-aware and escalates**: the template
  designer understands layout areas (it assigns compact sections to the
  sidebar and narrative ones to main, with layout↔area consistency
  normalization), the polish loop's structural escape hatch first tries
  a modified copy of the current template before drafting from scratch
  (modified → fresh ladder, one extra review iteration while a judgement
  is pending), and template picking renders candidate page thumbnails so
  the AI ranks the actual look when the PDF engine is present.
- **AI runs and Notes consolidated into one toolbar entry**: the separate
  "Notes" button is gone — when the CV carries an AI polish trace, its
  full review log (request, per-iteration issues/ops/coverage) renders at
  the top of the AI runs panel; the toolbar button badges "· Notes" so
  the trace is discoverable without a second control.
- **Profile experience summary is kind-split with a workspace button**:
  the Experience section on the profile page now groups its entries under
  labelled sub-sections (Jobs, Internships, Freelance, Projects,
  Volunteering — each with a count) instead of one flat latest-three list,
  and the workspace entry is a proper outline button in the card header.
- **Builder tool panel unified on the left with a picker menu**: the
  context panel (and the cover-letter brief) moved into the inspector as
  its first tab, and the six inspector areas (Context, Design, Template,
  Sections, AI, Lint) now live in a dropdown picker instead of a cramped
  tab row — the canvas gets the full center, and the docked chatbot has
  a clear home as an optional right column (open it from the toolbar's
  assistant button; the mobile pane switcher is now preview/panel only).
- **AI-generated CVs pick relevant skills only and drop skill levels**:
  the section planner is now instructed to select only the skills
  relevant to the target role (8-16) instead of listing every profile
  skill, generated skills blocks default to level-free display, and the
  run's skills intent (subset, levels off, cap) now overrides the
  template's skills props instead of being silently inherited.

### Fixed
- **Your message shows instantly when you send it** (plan 94): the user
  bubble appears in the transcript the moment you hit send, not after the
  reply finishes streaming.
- **Sidebar templates paint the full page** (plan 92): on
  sidebar-layout templates the colored side panel ran out where its
  content ended, leaving a white strip at the bottom of the page — it
  now always spans the full page height, on screen and in the printed
  PDF. Full-height side panels also drop their rounded corners.
- **Chat bubbles softened**: one-line messages no longer render as
  capsules — bubbles use the standard corner radius with the small tail
  corner, and session-list titles wrap to two lines before truncating.
- **Language CEFR bands follow the certificate, not just the self-reported
  level**: when the "Show CEFR band" toggle is on and your latest
  proficiency certificate for a language declares a higher band than the
  profile level implies (e.g. an ECPE certificate proving C2 while the
  profile says advanced → C1), the CV now shows the certificate's band
  ("English — advanced (C2)"). Upgrade-only — an older lower-band
  certificate never downgrades your claim, "native" stays untouched, and
  a certificate band fills the gap when no level is set. Applies to the
  rendered CV and every text export.
- **Starred variants that can't render now say why** (projects included):
  starring a variant whose row is still a draft — or one archived when a
  newer activation retired the slot — used to fail silently and the CV
  kept showing the original text. The builder lint now warns
  ("synth_pin_inactive") naming the item and the reason (draft /
  archived / language or posting mismatch), and the context panel shows a
  visible "pin inactive" badge on the item.
- **Chat turns no longer fail with "Expecting value: line 1 column 1"**
  (plan 82C): whitespace-only model replies now trigger the non-streaming
  fallback, a reply that arrives as plain prose gets one automatic
  non-streaming retry, and a genuine failure surfaces a clear, retryable
  message (naming the token cap when the reply was truncated) instead of a
  raw JSON parse error. The model's raw output is now recorded on the
  audit trail when a reply can't be parsed, making flaky-provider
  diagnosis possible after the fact.
- **Chat turns no longer die on "Expecting value: line 1 column 1"**:
  when a model streams zero text chunks (safety-blocked replies, or the
  answer landing outside the text parts), the structured stream used to
  fail on `json.loads("")` — it now retries once without streaming and,
  if the model still returns nothing, fails with an explicit
  "model returned no text content — please retry" message instead of a
  JSON parser error. Two GitHub links in one message also no longer
  overwrite each other's grounding, and a failed turn now still shows
  your just-sent user message in the transcript (it was persisted
  server-side all along — only the failed reply was missing).
- **Skipped suggestions now say why**: when a chat turn proposes a
  profile change that fails validation, the turn's note no longer stops
  at "N suggestion(s) skipped — the data didn't validate" — the
  per-op validation reason is persisted with the message and rendered
  right under that note (e.g. "experience_item: end is required unless
  open_ended"), so a bad model payload is diagnosable from the chat
  itself instead of only in the backend log.
- **Experience ops with loose model shapes now become cards**: models
  routinely propose skills/achievements/links as label strings
  (`skills: ["electron", …]`) or `{name: …}` dicts; those ops used to
  drop with 5 raw validation errors — chat-sourced payloads now
  normalize (`{skill_key}`, `{text}`, `{url}`) so the card renders and
  approval find-or-proposes the free-text skills. **Also fixed a latent
  async crash**: a proposal update touching an experience item's
  `skills`/`achievements` fields hit lazy relationship loads and killed
  the whole turn with a greenlet error — the diff loader now
  eager-loads both collections.
- **Cleaner update-card diffs**: the "before" side of an update card's
  `skills`/`achievements` rows no longer renders the raw SQLAlchemy
  repr (`<app.models.experience_model.ExperienceSkill object at
  0x…>`) — relationship collections serialize as payload-shaped dicts,
  and unchanged skill sets drop out of the diff entirely instead of
  showing same-content noise.
- **Proposal cards render skills/links as chips**: experience proposal
  diffs now carry scalar lists (skill keys, achievement texts, link
  urls) instead of raw payload JSON — the card body renders them as
  tidy chips via the library's parsed-detail renderer, on create and
  update cards alike, and update cards skip unchanged collections
  instead of printing identical JSON on both sides.
- **Chatbot project proposals no longer silently dropped**: when a real
  model proposed new experience items without dates (the common case for
  "add project X" turns), every card used to fail the experience-item
  date validation and the turn only reported "N suggestion(s) skipped —
  the data didn't validate". Undated creates now normalize to
  open-ended (`open_ended: true`) so the card appears for review, the
  chatbot prompt teaches the exact payload rule, and dropped ops are
  logged with their validation reason for diagnosis.
- **"Create new items" turns now ground the profile digests**: edit
  requests that name no entity kind ("create new items and update
  existing too") still pull the read-only profile digests so update ops
  get their verbatim ids, and the prompt spells out that create ops
  never need ids or a digest — the model no longer answers such turns
  with copy-paste text instead of proposal cards.
- **Session-scoped profile digest cache**: profile digests read for edit
  grounding now persist on the chat session instead of vanishing between
  turns — one keyword-bearing message ("tell me about my projects")
  primes the cache, and every later turn ("update the existing ones")
  is grounded even with zero keyword matches. Freshness is data-anchored:
  a `(count, max(updated_at))` signature over each digest's source
  tables is checked per turn, so approving a card (or any profile edit
  from any path) auto-refreshes the affected digest — no TTLs, no
  invalidation hooks. The turn trace distinguishes fresh reads from
  cached reuse, and the session API never exposes cached payloads.
- **Accurate CV page counts — the printed PDF is now the truth**: the
  polish loop, lint and copilot visual review used to count pages from
  screenshot-clipped scroll height, which ignored `@page` margins and CSS
  print fragmentation and could pass a CV that exports a page over
  budget. Every measurement now prints the document once through
  Chromium and counts the PDF's own page tree (pypdfium2) — the count is
  never clamped (a 6-page CV over a 4-image cap used to read as 4), and
  the vision critique receives the exact printed pages rasterized from
  that PDF. Lint prefers a live print of the current state over the last
  export's stamp, which aged with every edit, and the CV Studio page chip
  distinguishes measured (`2/2 pages`) from estimated
  (`~2/2 pages (unverified)`) counts. One persistent browser now serves
  exports, reviews and lint (previously one cold launch per call) and
  closes itself when idle.
- **Desktop builds ship a working PDF engine**: Linux deb/AppImage
  bundles now include the Chromium headless shell (deb gained the nss/
  alsa/gbm runtime dependencies), the Windows executable uses the
  installed Edge/Chrome via Playwright channels, and `run-dev.sh`
  bootstraps the engine for dev parity. `careerassistant enginecheck`
  (also run as a release smoke on every platform) reports engine health;
  without any engine, export still degrades to the print view and page
  counts are explicitly flagged unverified.
- Fixed the ATS lint overflow warning printing "exceed max None" —
  `RenderMetrics` now carries the real page budget.
- **Variants for every section**: gap-variant generation covers projects
  and volunteering now (plan-70's v1 trio lifted) — the planner can
  propose synthesized variants for any item source (work experience,
  projects, volunteering, education, certifications), the plan prompt
  names them explicitly (≤3 per run), and the polish loop's variant
  grounding stays source-agnostic.
- **The gate's last bypass is closed**: two more paths let an
  over-budget CV through — the routing gate read only fail-level
  *checks* (not the budget metric) and a blocking lint fact alongside
  an empty vision critique still finalized. Now `route_after_review`
  blocks whenever `pages_actual_over_budget` is set (measured or
  estimated, engine or not), and blocking lint facts always route to
  `fix` — accept-last-passed can no longer happen on a page overflow.
- **The PDF engine check lied inside the async app**: `pdf_engine_available()`
  probes Playwright with the *sync* API, which always raises inside the
  running asyncio loop — swallowed, so every gated capability silently
  degraded: live page measurement, polish vision captures, template
  thumbnails. That's why the fresh CV said "1 page" while the PDF
  export (ungated async path) measured 1.5 — and why scrolling to the
  tail only started working after the export stamped its page count.
  All async callers now attempt the render directly and catch
  `PDFEngineUnavailable`/flakiness; the capability probe is gone.
- **Over-budget builds can no longer slip past the gate**: the measured
  page-count overflow was only a warn — the LLM reviewer could
  effectively ignore it and the loop finalized ("~2/1 page" accepted).
  A measured over-budget is now a blocking, deterministic lint fail:
  the loop keeps densifying/compacting every round until the cap, and
  a capped run visibly reports the standing failure instead of a
  completed checkmark.
- **The page badge trusts measurements**: the builder toolbar now shows
  lint's measured page count (`pages_actual`) when the PDF engine has
  measured it, instead of the renderer estimate that lied for dense
  layouts — the badge and the budget over/under now match what export
  produces.
- **No more double scrollbars in the CV preview**: the preview iframe's
  inner document can never grow its own scrollbar now (`overflow:
  hidden` inside the frame + native `scrolling="no"`) — the outer zoom
  canvas is the only scroller.
- **The loop measures the REAL page count now**: the renderer's line
  estimate drifts for dense two-column layouts (studio showed "~1 page"
  while the PDF export was ~1.5) — so the polish gate accepted an
  overflowing CV. With the PDF engine present, lint measures the actual
  rendered page count live instead of trusting the estimate, so the
  over-budget fail stands and the loop keeps compaction going.
- **Grounded variants get more compact on repeat rounds**: the polish
  loop's variant grounding is a `restyle` at `short` length and now
  grounds from the CV's *current* rendered text (the applied override)
  rather than the raw profile item — each redraft tightens the previous
  one instead of re-tailoring from scratch. The copilot can also edit
  variant text directly (`cv_synth_update` — "make variant X tighter"),
  and a kept variant is active + starred, so it feeds the next run.
- **Contact details never split across lines**: CV contact items
  (email, phone, links) render one piece per line — a link that won't
  fit truncates with an ellipsis instead of breaking mid-string in both
  the icon and the plain-text header variants.
- **Every review round sees the full state**: the polish reviewer's
  prompt now carries which items lean on a synthesized variant
  (`synth_applied`) or a manual override (`override_fields`), plus the
  relevant block props (skills selection + rendering style, item
  ordering, sidebar assignment) — critique and fixes can reason about
  the actual CV state, not just page pixels and lint ids.
- **The page budget stays the budget**: an AI polish run with a 1-page
  constraint no longer "fixes" the overflow by quietly raising the
  budget to 2 — the reviewer is told (and the fix applier now
  enforces) that `max_pages` never grows; over-budget builds get
  content-trim suggestions instead, and a rejected widen shows in the
  run trace.
- **A "modern" brief actually shapes the build**: the polish reviewer
  now receives the user's emphasis notes, so asking for a modern /
  sidepanel layout can surface as a layout finding (feeding the
  template redesign ladder), and the template picker treats
  sidebar/modern/two-column wording in the notes as a real layout
  preference — sidebar candidates top the ranking instead of the
  plain single-column default.
- **Variants always land linked**: AI-generated synth variants no
  longer vanish when the model fails to echo its source citations — a
  single-source generation persists under the authoritative request
  refs (marked unverified until the citation checks out), and partial/
  out-of-allowlist citations keep only the valid subset instead of
  dropping the whole row. Variant grounding failures inside the polish
  loop also degrade to a run warning instead of crashing the run.
- **Vision review actually sees the pages now**: the screenshot path
  clipped beyond the viewport for CVs spilling past one page ("Clipped
  area is either empty or outside the resulting image") — every
  multi-page review silently degraded to lint-only facts. The capture
  now spans the full document.
- **Bullets-only rewrites are no longer dropped**: a draft that lands as
  achievement bullets (no paragraph text) counted as empty and the
  section silently fell back to the unformatted profile text — the
  "rewrite anything needed" ask appeared ignored. Bullets now count as
  usable content, and when a section still falls back the run's
  warnings name the exact reason (visible in the AI runs panel).
- **An About section can be generated**: asking for an "about"/profile
  narrative in the emphasis notes makes the planner add an About
  section, drafted as a first-person paragraph into a custom-text block.
- **AI template pick now honors the emphasis notes**: the generate
  modal's "what should this CV emphasize" text reaches the template
  ranking prompt (previously it was dropped — the pick ranked on
  metadata alone and the sidebar+ATS baseline always crowned the same
  template); the ranking is also instructed to weigh the emphasis and
  target role when reordering.
- **CV import no longer duplicates certifications**: re-intaking the same
  CV created a second copy of every certification (the renderer then
  printed each pair twice); the intake apply now dedupes on name +
  issuer, case-insensitive, reporting skipped duplicates like experience
  items already do.
- **Section-order lint is area-aware**: sidebar layouts render the
  sidebar column before/after the main flow — the lint now compares
  against that reading order instead of failing every sidebar template
  whose sidebar blocks aren't stored at the edges.
- **Experience workspace no longer crashes on startless projects**: a
  project saved without a start date crashed the whole `/profile/experience`
  page on render (the period line assumed `start` is always set — the
  backend deliberately allows null starts for projects). The list now
  renders an empty period segment instead.
- **CV import no longer duplicates certifications**: re-intaking the same
  CV created a second copy of every certification (the renderer then
  printed each pair twice); the intake apply now dedupes on name +
  issuer, case-insensitive, reporting skipped duplicates like experience
  items already do.
  fallbacks, rejected ops, degraded subsystems) reach stderr in every
  launch mode — uvicorn only configured its own loggers and the desktop
  shell none, so AI-flow failures could vanish silently.
- **CV Builder chat no longer produces untitled sections**: sections added
  by the assistant now get the block registry's defaults (e.g. "Skills")
  instead of an empty title, and the Sections panel falls back to the
  translated block name instead of showing a raw `templateEditor…` key.
- **Profile page navigation no longer jumps around**: the section rail
  sticks flush under the app header and, being taller than short
  viewports with its 15 sections, scrolls internally instead of
  pushing its bottom items below the fold; switching tabs scrolls the
  content pane back to top, so every tab starts in the same place.
  The Settings page nav gets the same treatment.
- **Startless projects no longer crash the profile Experience tab**: the
  summary card sliced an absent start date; entries without dates now
  render a "no dates" badge instead of a blank page.
- **Adding a project without dates no longer breaks the app**: projects
  are the one experience kind allowed to omit a start date, but the
  career-stage heuristic, profile snapshot and skill derivation still
  assumed it was set — crashing `/me/bootstrap` (and with it the whole
  dashboard) with a 500. Startless items now contribute no evidence
  window instead of crashing.
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
