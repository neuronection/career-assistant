# Changelog

All notable changes to **Career Assistant** are documented here.

## [Unreleased]

### Changed
- **AI settings rebuilt on the family UI library, part 1 of 3 (Models tab)** —
  the Models tab is now the family's `ModelRegistry` module: provider cards
  with chevron tiles and enabled/total pills, registered-model rows with
  capability chips (guessed from the model id and toggleable), a searchable
  catalog modal with manual-id entry and add-all, and clearable
  temperature/max-tokens fields at add time. Reading is unchanged; editing an
  existing model is still pending a backend per-model update endpoint and
  reports an explanatory note. `@neuronection/assistant-ui` moves to
  `^0.13.1` (pending library release carries the read-only provider flag —
  see the release note in the final adoption report).
- **Internal identifier rebrand** — environment variables
  (`CAREER_SKIP_SEED`, `CAREER_ENV_FILE`), the browser session-storage
  key, and the local dev-database identifiers (compose project
  `career`, DBs `career`/`career_test`, user/password defaults) now follow
  the product name. Self-hosters with custom env files or pinned dev
  databases: rename the variables and recreate the dev DB (a dump/restore
  preserves data). Browser sessions start fresh (re-login required).

### Added
- **Postings Explore, detail & chat tools (Phase 32)** — live vacancies
  become a first-class, explorable surface. The **Explore page** filters
  over every structured field — free text, skill+level (with all/any and
  priority), posted windows, salary floor, seniority, work mode, sources
  and deep-extracted-only — with **live facet badges** (self-excluding,
  so counts stay honest while you filter), cursor pagination and a
  **"Save this search"** button that persists the filter set and makes it
  schedulable (the saved-search runner now evaluates the full filter
  vocabulary). The posting detail view gains a **per-posting match score**
  — deterministic dimensions over the extracted data (skills with levels,
  prerequisites, location/remote, seniority vs your stage, freshness),
  weighted by your fit sliders and cached with staleness detection;
  unextracted postings show the archetype estimate with a visible note.
  Every posting carries a **short reference id** (e.g. `P3KX9Q2A`) shown
  on the detail view and cards, resolvable by chat. The chatbot gains
  posting tools — search open roles (by source board, recency, seniority,
  remote), open a posting by reference id, find similar postings — with
  cards deep-linking into the app, an "Open in Explore" action for any
  filter set it builds, source citation in every answer, and honest
  "source not configured" replies.
- **Deep posting extraction & skill-level search (Phase 31)** — every
  posting becomes fully structured, auditable data. A queued LLM pass
  (`posting_extract`, one audited structured call per posting through the
  background queue) pulls out **skills with required level 1–10, priority
  (must-have / nice-to-have / bonus) and a mandatory evidence quote**,
  seniority, salary, education, languages, benefits and responsibilities
  with time splits. Sync never blocks: the plan-26 fast pass still runs
  inline, deep extraction queues behind it with **demand-driven priority**
  (postings matching your alert rules extract first; the rest drip in the
  background) and `extract_version` staleness re-extracts when the
  prompt/model bumps. Fields the model can't support are suppressed
  below a confidence threshold and flagged for moderation — never guessed
  silently; unmappable skills become taxonomy proposals instead of being
  dropped. The payoff: **search postings by "skill X at level ≥ N"**
  (`/postings/search?skills=sql:4,python:3`, all/any semantics, priority
  filter), a **"match my profile" ranking** on the same deterministic
  curve as your fit score, skill+level pickers in the Live tab filter bar,
  and a posting detail view with level dots, priority badges, evidence
  quotes on tap and a provenance indicator (raw → fast-mapped → extracted).
- **Desktop background mode (Phase 30)** — close the window, keep working.
  Closing the desktop app hides it to the **system tray** (opt-in via a
  first-run prompt; configurable any time) while the server, scheduler and
  job queue keep running — scheduled searches, source syncs and digests
  continue in the background, and quitting from the tray menu drains the
  queue gracefully before exit. A **single-instance lock** (lockfile +
  socket handshake in the data dir) makes a second launch focus the
  running window instead of double-binding, with stale-lock recovery.
  **Auto-start on login** (opt-in: Linux autostart file, Windows Run key,
  macOS launch agent) boots tray-only via `app --tray`. Native
  notifications are a **channel consumer of the existing notification
  funnel** — nothing creates its own alerts: toasts render through the
  pywebview bridge (OS notification with in-app fallback), quiet hours are
  honored on both sides, misfired schedules surface as catch-up toasts on
  boot, and clicking a toast focuses the window and deep-links to the
  item (dismissing marks nothing — "mark all read" lives in the tray
  menu, which also exposes Open · Sync now · Saved searches ·
  Notifications). One build, capabilities declared: the bootstrap payload
  announces `in_app + desktop` channels in desktop mode vs
  `in_app + browser` on the web. Missing pystray/AppIndicator degrades to
  window-only mode — never a crash.
- **Modular scheduler (Phase 29)** — one robust engine for everything
  periodic, replacing the first-login/on-boot/manual-refresh workarounds:
  a `schedules` table (kind, typed trigger, payload, misfire policy,
  failure counters, unique kind+owner+payload-hash) and a **trigger
  registry** with the same plugin pattern as connectors — built-ins
  `interval` (+jitter), `daily_at`/`weekly` (IANA timezones, DST-safe),
  a dependency-free **5-field cron parser** (lists/ranges/steps,
  malformed expressions rejected) and `boot_stale` — third parties
  register more via the `career_assistant.scheduler_triggers` entry-point
  group. A single asyncio loop in the app lifespan (identical for web and
  desktop) claims due schedules and **only enqueues plan-12 jobs** — the
  scheduler decides WHEN, the queue decides WHAT/HOW. Overlap guard (no
  piling when the last job is still queued/running), misfire policies
  (`asap` fires missed runs once, `skip`/`next_slot` advance) for
  desktop sleep, and an exponential **failure backoff ladder** that
  alerts admins (system schedules) or the user after repeated failures
  through the `background_failed` kind. **Scheduled saved searches**
  ("the app searches for me"): saved postings searches gain schedule
  options (off / every N hours / daily / weekly) — runs evaluate the
  filters and notify only on new matches; **weekly digests** land as
  per-user schedules composing new-posting counts + near-miss radar
  through the `digest_ready` kind; the quarterly **check-in** and the
  fit-version **refit sweep** move onto the scheduler. Settings →
  Scheduler: run-now/pause for system schedules (admins) and a schedule
  editor for saved searches, with next-run previews.
- **Growth toolkit (Phase 28)** — the app stays valuable after the job is
  found. **Growth roadmaps** (`/growth`): target a job and skill gaps +
  curated path steps become an editable, reorderable step list — completing
  a skill step self-reports the level, upserts your skills (conflicts
  flagged, never silently overwritten) and **re-fits the whole catalog**, so
  step done → fit moves, visibly. The **near-miss radar** (deterministic,
  no AI) surfaces adjacent roles in the 5.5–7.5 fit band where the missing
  mass is few discrete skills ("1 skill away from ML Engineer: Python +2")
  and never shows hard-gated jobs. **Learning resources** attach to skills
  (https-only, admin CRUD, AI suggestions land as drafts for moderation)
  and appear inside roadmap steps. The **market snapshot** aggregates live
  postings per job/family — volume trend, p25–p75 salary band (suppressed
  under thin samples, N always shown), top employers and most-demanded
  skills (pure analytics, never a fit input) — on JobDetail and Target
  mode. **Quarterly check-ins** (stage confirm + micro skill self-report
  with conflict surfacing, skippable +3 months) with a banner when due.
  **Quiet hours** on alert rules keep pings inside your window — employed-
  user discretion, nothing social or sharable exists by design.
- **Express start & target mode (Phase 27)** — the second front door for
  people who arrive knowing their target job: type a title, the
  **resolver** matches catalog archetypes deterministically first
  (skills.aliases + trigram title matching, taxonomy keys only) with an
  audited AI fallback (`AITaskType.TARGET_RESOLVE`), and
  `POST /onboarding/express` wires everything in one call — 1–3 targets,
  location/remote + stage suggestion into a sparse profile, interests
  written with `source=express` (later assessments merge cleanly on the
  same tables), and scoped `new_posting_match` + `fit_threshold` alert
  rules. Straight into a **target-mode Dashboard**: open postings unseen-
  first (plan 22 fairness keeps sparse profiles rankable — no zeroing), a
  market snapshot (volume, salary band, top employers, honest empty
  states), "expand your career" adjacent targets from
  `similar_to`/`specialises_into` edges, a **profile-completeness ring**
  (`GET /me/completeness` — every gap links to its fix), and contextual
  **micro-run nudges** reusing plan-23 custom runs with a global cooldown
  and dismiss-forever semantics.
- **Live postings & connector SDK (Phase 26)** — real vacancies, legally:
  a pluggable **connector SDK** (`app/connectors/`) with five first-party
  engines (Greenhouse/Lever/Ashby **ATS public APIs**, schema.org
  **JSON-LD**, **RSS/Atom**, **CSV**, paste-a-**URL**), entry-point plugin
  discovery (admin allowlist — plugins run in-process, so they're opt-in;
  desktop ships built-ins only), and a **contract test kit** that ships in
  the package so third parties can verify config round-trips, stateless
  fetch idempotence, external_id stability and capability honesty.
  Politeness is structural: connectors never open sockets — the runtime
  injects the transport and enforces conditional GET (ETag/Last-Modified)
  and sync-state cursors. Postings flow through the existing stack:
  skill-ID intersection mapping onto catalog archetypes (keyword/alias
  index → audited AI extractor → FK-only `posting_skills` edges — **never
  label matching**, below-threshold falls to moderation; human mapping
  wins forever), deterministic fit = catalog fit + freshness/remote/
  seniority-vs-stage deltas with **zero per-posting AI**, unseen-first
  **Live tab** with source badges, save/hide/apply tracking (applied fires
  when you open the original URL), a saved→applied **applications widget**
  on the Dashboard, `search_history` scope `postings`, and a
  **new_posting_match** alert kind reusing plan 24's rules + dedup +
  cooldown machinery. Sync runs through the plan-12 queue (manual refresh;
  plan 29 schedules it later); an expiry sweep retires postings after
  `expires_at` or 45 days. Plan-42 discipline applied: every hot filter
  field is a real indexed column (seniority, onsite policy, salary as
  NUMERIC + ISO currency + period), JSONB keeps content only.
- **Career stages (Phase 25)** — Career Assistant is no longer
  student-only. One first-class concept — the **career stage**
  (`student` / `early_career` / `experienced` / `switching` / `returning`,
  stored on profile basics) — hangs every audience adaptation off it:
  unset stages are **derived** from an age/education/experience heuristic
  and always user-correctable (birth-year validation now accepts anyone
  14+; `grade`/GPA are student-only and silently dropped for everyone
  else). The fit engine gains **per-stage weight presets** applied as
  *suggested sliders* — never hidden scoring branches: stored user weights
  always win, and switching stage in the profile page re-applies the
  preset and refits the whole catalog deterministically. The assessment
  pipeline becomes stage-aware without changing shape: bank questions
  carry `audience_stages` (students see campus scenarios, returners see
  re-entry ones from the same bank), and the AI scenario designer's prompt
  now asks a switcher about transferable skills and a returner about
  re-entry gaps. Universities are a **stage-gated module**: the nav entry
  and dashboard shortcut disappear for non-students behind a
  `GET /me/bootstrap` feature-flag payload (`universities`, `grade_fields`)
  — the same flag pattern plan 36 uses for channels. Career paths for
  non-students reorder experience/certification steps ahead of
  education-heavy routes (an ordering rule, no new data). Onboarding asks
  stage as its first question and adapts copy; the dashboard speaks to the
  stage you're in.
- **Engagement & notifications (Phase 24)** — the daily-use loop closes:
  **search history** remembers your catalog/rankings/universities searches
  (server-side 30-minute debounce, 200-row cap with saved searches never
  pruned), a recent-searches dropdown on Catalog and Rankings re-runs any
  past search — filters included — in one click, and searches can be saved
  for future alert rules (plan 29). A **discovery feed** (`GET /feed`)
  orders the catalog unseen-first by fit, marks impressions in batch (insight
  rows are lazily created), and reserves one **exploration slot** per first
  page for the best unseen job from a family you haven't seen — plan 22's
  deferred diversity pick, finally powered by seen-state. Bookmarks (saved
  view) and hide (pure feed curation — your dismissed *status* stays
  semantic) live on JobDetail and the Dashboard; unseen counters badge the
  feed. Jobs gain curated **direct-application links** (`jobs.links`,
  https-only allowlist, shown with the education requirement on JobDetail and
  an education chip on every JobCard) and the interest taxonomy gains a
  `kind` (topic vs industry) without a second vocabulary. **Alert rules**
  arrive with guardrails: the default rule (fit ≥ 7, max 5/day, 7-day
  per-job cooldown) fires `fit_threshold` notifications the moment your
  stored fit crosses the line — re-alerting only when the score moves ≥ 0.5,
  mappable per family — while `new_in_family` pings you when a job publishes
  in a family you follow. Everything emits through a seeded
  `notification_kinds` registry (plan-42 typed-ref rule; plan 36 replaces the
  storage with the unified fan-out stack and keeps these semantics). A
  notification bell with unread badge, mark-read and inline rule controls
  sits in the header.
- **JobTypeMatch assessment engine (Phase 23)** — the 4-phase profiling flow
  (profile foundation → standardized scenarios → AI-generated scenarios →
  personalized selection) runs as a **composable phase pipeline**, not
  hardcoded screens: runs are resumable forever (save-on-answer, skip
  allowed — skips are neutral, never zeroing), custom runs re-run any subset
  of phases 2–4 with a focus context, and history keeps every run diffable.
  A seeded question bank (scenario MCQs, 100%-summing time allocations,
  ranking items) spans ≥3 job families per question — no binary either/or,
  enforced by a checklist test. The new **assessment_designer** AI agent
  drafts personalized scenarios validated onto taxonomy keys (unresolvable
  keys are dropped; generation failure degrades gracefully to bank
  questions). Completion **reconciles evidence**: assessed skill levels
  upsert `user_skills` (source=assessment) while divergences >2 levels from
  your self-rating are flagged ("keep which?") instead of silently
  overwriting; interests merge into the profile; a fit refresh + AI
  rationale for the top-N lands in the queue. A per-question **"Ask"
  helper** explains any question via the audited quick-assist agent. New
  `/assessment` wizard UI: progress rail, structured question cards
  (allocation sliders with live 100% check, up/down rank lists), results
  view with revealed skills + refreshed shortlist + conflict panel.
- **Deterministic fit engine (Phase 22)** — every user×job pair now gets a
  transparent 0–10 **fit score** with a per-dimension breakdown (skills,
  education, experience, location, interests + work-style), computed by pure
  functions with zero AI cost: skills coverage is importance-weighted with
  surplus never inflating and unknown skills redistributing weight instead of
  zeroing; education treats one-level-short as "in progress"; experience
  evidence is kind-weighted (projects count fractionally) against a new
  `experience_typical_years` band and is **never punished for missing signal**
  (neutral 7); hard-constraint gates (physical, education-years) remove jobs
  from the default feed into a "Stretch goals" view with explanations — never
  silently deleted. Rare-job fairness is explicit and tested: no
  popularity/impression/family-size term anywhere, and demand is a plain
  opt-in sort, never a multiplier — the old combined formula and `base_score`
  are deleted outright. New **weight sliders** (1–5 per dimension) refit the
  whole catalog on save with no AI calls; the AI rationale layer now explains
  the **top-N by fit** instead of scoring blind. Profile gains experience +
  preferences sections; `match_insights` gains `fit_score`, `fit_breakdown`
  and `fit_version` (formula bumps mark stored fits stale). Rankings show
  breakdown bars, "why?" explanations and "Strong in X" specialist
  highlights; JobDetail explains a job fit dimension by dimension.
- **Skill ontology (Phase 21)** — `skill_tags` becomes a real `skills`
  ontology: self-referencing subskills, semantic **1–10 level anchors**
  (novice / guided / independent / expert, AI can draft per-skill anchors),
  display aliases, and a proper lifecycle (`proposed` → `active` →
  `deprecated`) with `origin` + `provenance`. Unknown skills never hard-fail:
  self-reporting an unlisted skill auto-creates a `proposed` row (origin
  user) that stays out of catalog filters until an admin promotes it;
  duplicates are resolved at proposal time via the alias index and merged
  with full join-table rewrite (aliases redirect, source row deprecated).
  Relations moved out of JSONB into FK join tables — `job_skills` (level +
  importance), `job_tags`, `user_skills`, `user_interests` — so overlaps are
  indexed SQL joins. **Career paths** are a product concept now: curated +
  AI-drafted routes to every job (via a new `path_suggester` agent on the
  background queue, admin publish/reject moderation), a cycle-safe computed
  graph of "jobs that lead here" over `leads_to`/`prerequisite_of` edges,
  and a per-skill gap report (`required vs your level` + next-step hints from
  published paths). New UI: profile **Skills editor** (1–10 sliders with
  anchors, searchable picker), JobDetail **Skills required** panel (level
  bars, suggestions, next steps) and **Your path to this job** panel, and
  Settings → Taxonomy with skills lifecycle management (promote / deprecate /
  merge) plus a Paths moderation tab. One destructive migration (data
  transformed in place; verified on PostgreSQL and SQLite round trips).
  A reference-discipline regression test bans label/title comparisons in
  application code — matching operates on ids and stable keys only.

### Fixed
- **Desktop toasts and focus actually reach the window on Linux**: the
  shell's own strict CSP (`script-src 'self'`) made WebKitGTK (and
  WebView2) refuse pywebview's `evaluate_js`, so notification pushes into
  the app window and the toast-activation focus silently failed. The
  shell now loads the SPA with a per-boot random `?shell=` token and the
  security headers middleware serves that document a desktop CSP variant
  (`'unsafe-eval'` on `script-src` only); browser and self-hosted web
  deployments keep the strict CSP unchanged.
- **Tray menu failed to build with real pystray**: menu actions carried a
  third parameter (pystray accepts at most two) and submenu construction
  used a non-existent `pystray.Submenu` class (submenus are a `Menu`
  passed as the item's action), so `app --tray` degraded to window-only
  mode with a `Tray init failed` warning.
- **Docker image waits for the database before migrating**: the entrypoint
  ran `alembic upgrade head` immediately, so a raw `docker run` beside a
  freshly started Postgres crashed with `ConnectionRefused` while Postgres
  was still initializing (compose deploys were already gated on
  `service_healthy`); the entrypoint now waits up to 60s for the database
  port.
- **CI Docker smoke test can run the image it just built**: buildx's
  container driver keeps `push: false` builds out of the local Docker image
  store, so the smoke step tried to pull `career-assistant:ci` from Docker
  Hub; the build now loads the image (`load: true`) before `docker run`.
- **CI smoke test no longer fails on its own 404 assertion**: the unknown-API
  route check used `curl -f`, which turns the *expected* 404 into a curl
  error; it now asserts the status code, JSON content type and body without
  `-f`.
- **Desktop scheduled backup no longer fires before the database exists**:
  the boot-time backup hook ran before migrations, logging a "Database file
  not found" traceback on every fresh install; it now runs after migrations
  and seeding.
- **Linux release pipeline installs the correct gdk-pixbuf tools package**:
  Ubuntu 24.04 names it `libgdk-pixbuf2.0-bin` (the dashed
  `libgdk-pixbuf-2.0-bin` only exists on Debian 13+), so the release job's
  `apt-get install` no longer fails. The builder also resolves
  `gdk-pixbuf-query-loaders` from its multiarch libdir — Ubuntu does not put
  it on `PATH` — so AppImage pixbuf-loader vendoring no longer silently
  skips.
- **SQLite (desktop) profile passes the full backend suite**: datetime
  columns now round-trip timezone-aware UTC values on every dialect
  (SQLite returned naive datetimes, crashing any `now - posted_at`
  comparison in the scheduler, postings fit and growth check-ins), the
  notification-kind seed inserts real UUID objects (SQLAlchemy's generic
  `Uuid` bind rejects raw strings), and archetype resolution orders
  families deterministically (`level, key`) instead of relying on
  Postgres' unspecified tie ordering. CI's new "Backend on SQLite
  (desktop profile)" job is green.

## [0.2.0] - 2026-08-30

### Fixed
- **Chat streaming actually renders**: the SSE reader parsed the buffer's
  incomplete remainder instead of the completed event blocks, so streamed
  tokens were dropped or fired as malformed partial JSON. Events are now
  reassembled across chunk boundaries (covered by a regression test).
- **Rate-limit identity can't be rotated via `X-Forwarded-For`**: the limiter
  trusted the leftmost forwarded hop, which clients control; it now keys on
  the rightmost hop — the address our own reverse proxy observed.
- **Desktop restore failures report the real cause**: a corrupt database
  inside a backup archive left files in the staging directory, so cleanup
  raised `ENOTEMPTY` and masked the underlying error; staging is now removed
  unconditionally and the live database is verified untouched by test.

### Added
- **Chat streaming (SSE)** — `POST /chat/sessions/{id}/messages?stream=true`
  streams the assistant reply live: `status` (catalog search) → `delta`
  (progressive answer text) → `meta` (referenced jobs) → `done`. The stream
  rides the same structured pipeline — the full output is validated against
  the schema and audited once on completion, no side door. The chat widget
  renders tokens as they arrive with an activity indicator, with a clean
  error event path; the non-streaming response is unchanged.
- **Admin surfaces** — Settings grows three admin-only sections plus a
  moderation queue: **Taxonomy** (create/edit/deprecate/delete interest and
  skill tags; keys are immutable slugs, referenced tags return `409` with
  reference counts and can be deprecated instead — deprecated tags stay
  resolvable everywhere but can be hidden from pickers), **Users** (list with
  match counts, promote/demote with last-admin and self-change guards,
  enable/disable, admin password reset, force logout — role and state changes
  revoke tokens immediately), **AI Audit** (filterable `ai_generations`
  viewer with token/latency detail), and a **Review queue** on the Generate
  page showing everyone's drafts with bulk publish/reject. Hand-created and
  AI-generated catalog entries now land as **drafts**; publishing is always
  an explicit step.
- **Data portability** — users own their data end to end:
  `POST /me/export` packages profile, match insights, chats and uploaded
  documents into a versioned zip (background job, live progress); download
  via `GET /background-jobs/{id}/download` (owner-only, attachment, archives
  auto-purge after 7 days). `DELETE /me` (password-confirmed) removes the
  account and *all* personal data via DB cascades — with a last-admin guard.
  Profile page gains a **Data & privacy** section (export + delete account).
  Self-host deployments get `scripts/backup.sh` / `restore.sh` (pg_dump +
  uploads volume) and an optional compose `backup` sidecar with retention.
  Desktop installs now back themselves up: consistent SQLite snapshot
  (`VACUUM INTO`) + uploads + `secret.key` under `<data_dir>/backups/`
  (14 daily + 8 weekly retention), a boot-time corruption guard that
  quarantines a broken DB and auto-restores the newest backup, plus
  `python -m careerassistant backup|restore ZIP` commands. SQLite now runs
  with `foreign_keys=ON`/WAL pragmas so cascades work on the desktop too.
- **Security hardening** — dependency-free per-IP rate limiting (sliding
  window: auth 10/min, AI 30/min per user, 240/min default; `429` +
  `Retry-After`), login brute-force **lockout** (5 failures → 15 min, `423`),
  JWT **revocation** via per-user `token_version` (new
  `POST /auth/revoke-sessions`; "Sign out everywhere" button on the profile
  page), hardened **security headers** on every response including a strict
  `Content-Security-Policy` for the SPA, and a 10-character password floor
  (configurable). Configurable via `RATE_LIMIT_*`, `LOCKOUT_*`,
  `PASSWORD_MIN_LENGTH` (see `.env.example`). CI runs `pip-audit` and
  `npm audit` as advisory checks.
- **Durable background jobs** — long AI work moved off the request path onto
  a claim-based queue (new `background_jobs` table, in-process workers, no
  Celery/Redis). University PDF parsing, AI job generation and batch match
  scoring now return `202` immediately with a job id; progress/stage are
  tracked per item and queryable via `GET /background-jobs[/{id}]` with
  cancellation support. Survives restarts (orphans are recovered or failed
  cleanly) and retries transient failures with a small backoff. The frontend
  polls job progress live on the Generate page and the university upload
  panel. Matching also gained a service-level split (`resolve_targets` /
  `score_one`) so the queue and endpoints share one scoring path.
- **Linux packaging & release pipeline** — `packaging/build-linux.sh`
  assembles a PyInstaller onedir bundle into a `.deb` and a fully
  self-contained `.AppImage` (vendored WebKit/GTK libs, pixbuf loaders,
  AppRun). Tag-triggered CI release workflow: version/tag match check,
  system WebKit deps, build, headless smoke test of the frozen binary
  (`/health`, SPA, JSON 404s), GitHub Release publication, plus a
  `ghcr.io` Docker image per version. Version is single-sourced in
  `backend/app/__init__.py` (`scripts/version_manager.py` to bump); the
  frozen app auto-detects its bundled SPA, alembic files and GI typelibs.
  CI also builds (and smokes) the bundle on every push to keep the
  toolchain green.
- **Desktop app mode (`python -m careerassistant`)** — the same app now runs
  as a local desktop application, ported from the Study Assistant shell:
  pywebview window (or `web` mode: loopback server + system browser) over a
  per-instance loopback server. The local profile stores everything under the
  platform data dir (`~/.local/share/CareerAssistant` on Linux): a **SQLite**
  database (`aiosqlite`), uploads, logs and a generated strong `secret.key`
  (never silently rewritten — it decrypts stored AI keys). Startup applies
  migrations and seeds the starter catalog automatically (`CAREER_SKIP_SEED=1`
  to opt out). Extras in `backend/requirements-desktop.txt`; the web/Docker
  stack is unchanged and still Postgres-first.
- **Cross-dialect database layer** — structured JSON columns now render as
  JSONB on PostgreSQL and JSON on SQLite from one shared type
  (`app.models.base.StructuredJSON`); job catalog JSON-path filters moved to
  portable Python-side evaluation; migrations are dialect-aware and verified
  on fresh PostgreSQL **and** SQLite databases. Timestamps are now written
  with sub-second precision on all dialects.
- **Test-isolation fix** — the AI provider/model/assignment tables were
  missing from the test reset list, leaking rows between tests on every
  backend run; the suite now wipes them (and runs green on both PostgreSQL
  and SQLite). CI gains a dedicated SQLite (desktop profile) backend job.
- Desktop smoke checks in CI cover `python -m careerassistant web` boot:
  migrations, `/health`, SPA serving and JSON 404s for unknown API paths.
- **Production self-host stack** — the backend now serves the built SPA
  (client-side routes fall back to `index.html`; unknown `/api/v1/*` paths
  still return JSON 404s), plus a multi-stage `docker/Dockerfile`,
  `docker/docker-compose.prod.yml` (app + Postgres, optional Caddy TLS-proxy
  profile), `docker/.env.production.example` template, healthcheck, and a
  full deployment guide ([docs/deploy.md](docs/deploy.md)) covering first
  boot, upgrades, backups, reverse proxies and bare-metal installs. CI gains
  a Docker job that builds the image and smoke-tests `/health` against a
  throwaway database. Configure via the new `SPA_DIST` setting (auto-detects
  by default).

### Changed
- **Logo redesign**: the icon now tells the career story — a briefcase origin,
  a dashed "road to the stars" rising to a dominant goal star (plus a small
  depth sparkle), with the road clearly separated from the case and phase-tuned
  so its final segment lands on the star. Balanced for legibility down to
  favicon size. Dark and light variants keep identical geometry; same
  filenames, no code changes.
- **Breaking: AI settings are UI/database-only** — all `AI_*` env vars are
  removed. Providers, models and task assignments live in the database and
  are managed in Settings → AI Configuration. Unconfigured production
  installs answer AI calls with 503 until an admin configures a provider;
  development auto-provisions a dev-only mock provider.
- **`APP_ENV` now defaults to `production`** (fail-safe). The `.env` file is
  always discovered (explicit `CAREER_ENV_FILE` or nearest walk-up hit);
  production boot guards (strong `JWT_SECRET`, `DEBUG=false`) enforce
  regardless of where configuration came from.

### Changed
- **Product naming + branding**: the app is now **Career Assistant** (part of
  the Health/Course/Career assistant family). New logo (career-path
  constellation SVG, light + dark
  variants), favicon, rebranded header/auth screens, page titles and
  package/health-endpoint names.

### Changed
- **Production readiness — mock AI is dev-only**: production refuses to boot
  with `AI_PROVIDER=mock`, a weak/default `JWT_SECRET` or `DEBUG=true`;
  mock providers cannot be created/selected outside development (API +
  settings UI hide the option); AI calls that would resolve to the mock
  provider in production fail with **503** and are audited — fake results
  can never be served in production.

### Added
- **Settings section** (`/settings`): two-pane shell with left nav (ported
  from Health-Assistant's SettingsShell) ready for future general settings;
  currently AI Configuration + Profile links.
- **AI Configuration page** with URL-synced tabs — **Providers**, **Models**,
  **Tasks** (like Health-Assistant's AIConfig):
  - Models tab: expandable per-provider cards (ModelsPage/ModelManager
    pattern) with "Add Model" that can browse the provider's live model
    catalog (`GET /ai/providers/{id}/fetch-external-models`, fuzzy-search
    dropdown, auto-beautified names) or enter ids manually; per-model
    connection tests.
  - Tasks tab: assignment cards (TaskAssignment pattern) showing
    "Provider / Model" per task with Mine/System Fallback badges and an
    inline grouped fuzzy-search model picker; clearing falls back to env
    defaults.
- New endpoints: `/ai/providers/{id}/fetch-external-models` and
  `/ai/models` (bulk, for assignment pickers).

### Added
- **AI settings architecture** (mirrors Health-Assistant): `ai_providers`
  (global/system + personal/user scopes, Fernet-encrypted API keys with
  `enc::` prefix and `***` preserve-marker), `ai_models` per provider, and
  per-task `ai_task_assignments`. Resolution order: user assignment →
  system assignment → `default` task → built-in env defaults. Every AI call
  (matching included) now runs on the resolved provider/model and is audited
  in `ai_generations`.
- **AI Settings page** (`/settings/ai`): Global/Personal tabs, provider CRUD
  with masked keys, model management, per-task assignment dropdowns with
  inheritance, and a connection test button. First registered user becomes
  admin (`users.is_admin`); system-scope changes require admin.
- Endpoints: `/ai/providers`, `/ai/providers/{id}/models`, `/ai/assignments/{task}`,
  `/ai/config/summary`, `/ai/test`, `/ai/tasks`.

### Added
- **Shared UI kit** (ported from Health-Assistant): Popover/Portal,
  SearchableDropdown (grouped + keyboard nav), DatePicker calendar,
  ScaleSlider, ChipInput/ChipList, Button, Card, Modal, ConfirmationModal,
  EmptyState, LoadingState, Table, RangeBar, InfoTooltip.
- **University detail page** with departments, admission baseline tables and
  a deadlines calendar; `application_deadline` on departments (extracted by
  the AI parser from uploaded catalogs, or set manually via DatePicker).
- Salary ranges visualized with RangeBar on the job detail page; rankings
  filters migrated to searchable dropdowns with an empty-state.

### Changed
- Onboarding likes/dislikes/hobbies/aspirations now use chip inputs;
  work-style and subject weights use gradient scale sliders.
- AI popup buttons render through portals (no more clipping inside cards).

### Fixed
- `scripts/run-dev.sh` no longer installs into the system Python (PEP 668);
  honcho/deps resolve inside `backend/venv`.

### Added
- **Auth & profiles**: JWT registration/login; deeply structured student
  profiles (basics, academics, interests, hobbies, likes/dislikes, aspirations,
  work-style scales, constraints) validated against controlled taxonomies.
- **Job catalog**: family tree + typed relation graph (similar/specialises/
  leads/alternative/prerequisite), 45 seeded jobs with fully structured
  attributes (interests, skills, education, physical, salary bands, demand,
  environments, typical pros/cons); search and rich filters.
- **AI layer**: provider abstraction (OpenAI-compatible endpoints or offline
  deterministic mock), six agents — job generator, relation suggester, match
  scorer, profile analyst, university parser, chatbot — all pydantic-validated
  and audited in `ai_generations`.
- **Matching**: AI 0–10 score with personalized positives/negatives and
  prerequisite checks (met/unmet/unknown), user rating + interest status,
  combined rankings with family/interest/demand/salary/education filters.
- **Universities**: manual entry or PDF intake (upload → AI parse → review →
  apply) creating universities, departments and yearly admission baselines;
  rich job↔department pathway links (relevance, required subjects, typical
  position, employment rate).
- **Chatbot**: floating chat widget with sessions, job deep-links and
  server-side catalog tools; contextual "Ask AI" popup buttons on job pages.
- **Frontend**: onboarding wizard, dashboard, catalog (tree + reactflow
  graph), job detail with scoring UI, AI generation page, universities page
  with document pipeline, rankings with score-distribution chart.
- Infra: docker dev-db (Postgres :5433 + Redis :6380), honcho Procfile,
  seed/test scripts; 60 backend tests + 16 frontend tests, ruff clean.
