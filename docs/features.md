# Feature catalog

Everything Career Assistant ships, as built. The [README](../README.md) is the
short version; this page is the reference. Statuses live in
[CHANGELOG.md](../CHANGELOG.md); the runtime architecture is in [ARCHITECTURE.md](ARCHITECTURE.md).

## Job catalog

- **Family tree + relation graph** — browse job families as a tree, then follow
  typed relations (`similar_to`, `specialises_into`, `leads_to`,
  `alternative_to`, `prerequisite_of`) in an interactive graph. Relations carry
  weight, rationale and source; the graph is first-class data, not UI
  decoration.
- **Rich structured attributes per job** — interests, skills, work style,
  education, physical demands, salary bands, demand outlook, environments,
  typical positives and negatives.
- **AI-generated jobs** — extend the catalog with new careers; the generator
  maps output onto the existing taxonomy so nothing becomes an orphan of free
  text.
- **Search and filter** across the whole catalog.

## Profile

- **Onboarding wizard** walks you through interests, skills, work-style
  preferences, education and constraints.
- **Start paths** — pick why you're here (explore careers, target a known job,
  start from your CV, or just browse) and answer only what your path needs.
- **Start from your CV** — upload an existing CV (PDF, text or photo); the
  intake pipeline reads it and you review what gets imported into your
  profile, from any point via **Profile → Import from CV**.
- **Everything is typed** — profile sections are structured JSONB validated
  against the taxonomy, so matching is computed, not vibes.
- **AI profile analysis** — get an external read on your profile and what it
  implies.

## Matching & rankings

- **Per-job match insights** — an AI score (0–10) with structured rationale:
  what fits (positives), what doesn't (negatives), and which prerequisites
  you're missing.
- **Your voice counts** — add your own score and interest status per job; AI
  and human scores coexist.
- **Filterable rankings** — combine AI score, your score and status, then
  slice by filters. Pick 2–4 jobs into the compare tray to see them side by
  side: per-dimension fit, gates, education, demand and salary (`/compare`),
  or ask the chatbot to compare them for you.
- **Deterministic fit engine** — every job gets a transparent 0–10 fit score
  with a per-dimension breakdown (skills, education, experience, location,
  interests + work style, work values) you can inspect and re-weight; interest
  scoring blends tag overlap with RIASEC affinity vectors, work values are
  scored against a job's derived signal (benefit kinds included), and
  hard-constraint gates move jobs to a "Stretch goals" view with explanations
  instead of deleting them. No popularity or demand term ever touches the
  score.
- **Express start & target mode** — already know the job you want? Type it,
  pick your targets, answer two questions — live postings, alerts and
  suggestions start immediately, with a target-mode dashboard (open jobs,
  salary band, top employers, adjacent careers) and a completeness ring that
  shows exactly which 5-minute step sharpens your results next.

## Universities & pathways

- **Upload your university admission PDF** — an AI parsing pipeline extracts
  universities, departments and yearly admission baselines into a reviewable
  draft.
- **You approve every write** — review, edit, then apply. Parsed data never
  lands in the catalog unreviewed.
- **Job ↔ department pathways** — departments link to jobs through rich link
  rows (relevance, required subjects, salary band, employment rate), so
  "which degree leads here?" has a real answer.
- **Career paths as data** — curated and AI-drafted routes to each job, with a
  computed graph of "jobs that lead here" over the typed relation edges.

## Postings & live search

- **Live postings, legally** — a connector SDK ships first-party engines for
  what's free and legal (ATS public APIs, schema.org JSON-LD, RSS, CSV,
  paste-a-URL) and lets anyone add more as plugins (admin-opt-in via the
  entry-point registry). Postings map onto the catalog by literal skill-ID
  intersection — never label matching — inherit your fit score with
  freshness/remote/seniority adjustments (no per-posting AI), flow through the
  same seen/saved/alerts machinery as the catalog, and track your
  saved→applied funnel.
- **Deep extraction & skill-level search** — a queued LLM pass turns postings
  into auditable data: skills with required level 1–10 and priority, each
  backed by a verbatim evidence quote, plus salary, responsibilities with time
  splits and seniority. Extraction v2 adds contract type, work hours, schedule
  cues, travel demand, onsite policy and typed benefits (each with its own
  evidence). Lifestyle constraints gate postings — flagged on the card, never
  hidden. Search vacancies by "skill X at level ≥ N", rank them by
  deterministic coverage of your skills, and read the provenance (raw →
  fast-mapped → extracted) on every card. Low-confidence fields are suppressed
  for review, never guessed.
- **Explore page** — filters every structured field (including contract type,
  travel, schedule cues, benefits and organization) with live facet counts,
  saves searches you can schedule, and paginates by cursor. Posting detail
  shows a per-posting match score built from the extracted data (weighted by
  your fit sliders, stale-proof), source attribution and similar roles.
- **Semantic search & skill packs** — postings embed into a portable vector
  store (pgvector optional, plain Postgres/SQLite fully supported); Explore's
  relevance search fuses lexical and semantic rankings without ever bypassing
  your hard filters. Task-steering AI instructions ship as versioned, audited
  skill packs.
- **Organizations are entities, not labels** — postings resolve onto a
  normalized organization through a matcher that folds legal-suffix and
  spelling variants into aliases; duplicates merge under admin review, and
  "top hiring orgs" aggregates by entity.

## Career Autopilot

Describe a goal once ("junior QA role, remote, €30k+") and an agent searches
your connected boards on a cadence or on demand: it plans multiple
query/filter variants, filters noise (seen/applied, never-terms, a per-goal
cooldown), ranks by your deterministic fit score, and delivers a curated
shortlist where every explanation cites verbatim quotes verified against the
posting's own text. A "what I searched & why" timeline shows each run's work;
budgets hard-cap runs (partials still ship); "more/hide like this" teaches the
goal's constraints, dismissing a whole shortlist pauses it, and three empty
runs trigger a refine-the-goal nudge — never wasted spend, never
auto-applying.

## Growth toolkit

The product works after you're hired:

- **Roadmaps** turn skill gaps into tracked steps (done → level self-report →
  catalog re-fit, visibly).
- **Near-miss radar** shows adjacent roles you're a couple of skills away
  from.
- **Learning resources** close the gaps.
- **Market snapshots** aggregate live postings per role (honest thin-sample
  handling).
- **Quarterly check-ins** and per-rule quiet hours keep it useful and
  discreet.

## Engagement loop

- **Discovery feed** ordered unseen-first by fit (with an exploration slot for
  families you haven't seen).
- **Search history** with one-click re-runs and saved searches.
- **Bookmarks and feed hiding** that never touch your semantic job status.
- **Curated https-only application links** beside the education requirement.
- **Threshold alerts** (fit ≥ your line, or new jobs in families you follow)
  with per-day caps, cooldowns and a kind registry — the substrate's
  multi-channel notification center builds on.

## Assessment & metric model

- **JobTypeMatch assessment** — a 4-phase profiling pipeline (profile
  foundation, standardized scenarios, AI-generated scenarios, personalized
  selection) with resumable runs, custom re-runs, and evidence reconciliation:
  scenario answers refine your skill levels while large conflicts with your
  self-rating are flagged, never silently overwritten.
- **One metric language** — a dimension registry (RIASEC interest affinities,
  work values, work style) stores what assessments, profile sections and
  behavior measure, with provenance; the fit engine, filters and weight
  sliders all speak it. Skill transferability ("your SQL transfers to 12 of 20
  families") derives from the catalog join graph.
- **Per-user metric profile** — RIASEC interest affinities, work-values fit
  dimension, lifestyle constraints with a salary-minimum gate, and per-skill
  transferability across job families.
- **Metric model residuals** — opt-in revealed preferences (engagement nudges
  your RIASEC vector by ≤5%/week, never the exploration slot) and an
  application outcome funnel per family (observation only — never scored).
- **Metric batteries** — RIASEC/values bank batteries in the assessment
  template library; engine dimension lists derive from one spec.

## Career stages

One switch (student, early career, experienced, switching, returning — derived
when unset, always correctable) retunes your suggested fit weights, asks
assessment scenarios grounded in your stage, reorders career paths
experience-first, and gates student-only modules like university intake behind
feature flags. The engine stays one engine: presets are suggestions, never
hidden scoring branches.

## CV Studio

Career Assistant is not just a CV builder, but this is its most mature
surface: a complete CV workspace where every AI action is grounded in your
structured profile.

- **Three ways to a CV** — build from **templates**: a versioned template bank
  rendered by one deterministic engine; start from an **existing CV**: upload
  yours (original preserved byte-for-byte, OCR text layer) and the AI intake
  pipeline turns it into a review-first draft you confirm item by item; or go
  **on-demand AI**: one-shot generation from your profile — pick context
  sources and preferences in a modal, a LangGraph draft flow plans and writes
  the whole CV with per-section fallbacks, it lands in the builder with an
  automatic restorable version, and an agentic **polish loop** critiques the
  rendered pages (vision + ATS lint + a coverage matrix) and applies fixes
  through the same audited path. The loop's round count is your choice
  (1–12 polish rounds), it can escalate a persistent style brief to the
  AI template designer (and per-section container overrides + an
  `elevation` token exist for expressive looks), template-version churn
  is coalesced per run, and an **enrich step** fetches a few of your own
  linked pages (GitHub repos, portfolios) on demand to ground the
  descriptions.
- **Per-CV context selection** — controls which profile items can render; the
  renderer snapshot carries per-item traceability, and AI writing (summaries,
  bullet rewrites, tailor-to-posting with must-have coverage,
  translate-assist) only sees what you included. Precedence:
  override > variant > source — and bullets are strictly two-layer:
  per-item bullets variants (pinned through their own slot) replace an
  item's achievement list; overrides never carry achievements.
- **Deep UI/template customization** — full design-token editor (colors,
  typography with embedded fonts, spacing per area, page margins, two-column
  newspaper flow, section heading icons, photo shapes, skill bars, grouped
  skill categories, page-2+ running headers/footers), a gallery that previews
  templates **with your own data** and a two-template compare view, live
  page-break rules in the canvas, and a printed-page visual review. Blocks are
  a registered kind system — every template is a validated version,
  import/export file-first (hash-verified).
- **Variant library** (`/cv/synth`) — AI-written or manual item variants
  (summarized, expanded, restyled, aimed at a posting, translated, steered by
  a custom instruction — including bullets-only variants that replace just
  an item's achievement list) that any CV can prefer over verbatim profile text;
  staleness is detected when the source changes, you star to activate, and a
  dedicated variant editor drafts fill-in-form with slot comparison against
  what's on the CV now, with an in-editor AI generate-fill.
- **Cover letters per posting** (coming soon — creation entry points are
  gated in the UI until the feature ships) — a deterministic brief (must-haves, fit, your
  goal), audited AI drafts that cite your evidence per paragraph with unbacked
  claims flagged, letters rendered through the same template engine with your
  CV's design tokens, and the same versions/exports as CVs.
- **Listing at a glance** — every CV card in the studio carries a first-page
  thumbnail printed by the same engine as the PDF (downscaled, cached per
  edit), the whole card opens the CV, and the list shows exactly your CVs —
  imported source files live in the import workspace, not here.
- **Honesty tools everywhere** — live ATS lint with a one-click score report,
  page-count meter with over-budget warnings, versions with diff/image-diff/
  restore, and exports to PDF/DOCX/Markdown/JSON/ATS text (the PDF is the
  page-count truth, via a real print engine). Drafts announce "review before
  exporting".

## The assistant (chat)

- **Chat grounded in the catalog** — the chatbot can search jobs, pull job
  details and look up your matches through tool-calling over your own data.
- **Proposals, never auto-apply** — profile changes open the item's full
  content before editing (a server-enforced read-before-edit gate), propose
  reviews as **proposal cards** with anchored, granular edits
  (unique-anchor replacements, additive appends, per-item skill/achievement
  add/remove — never full-blob rewrites), a rendered **before/after preview**
  with the changed span highlighted, and **one-click revert** after you
  approve; every change stays a signed review card.
- **Contextual "Ask AI" buttons** — quick-assist endpoints power one-click
  explanations wherever they're useful in the UI.
- **Builder copilot** — the main chat takes CVs as per-message reference
  attachments and hands off to the builder copilot on build intent: it applies
  templates, restyles tokens, edits sections and rewrites items as validated
  operations on one audited path shared with UI buttons, **sees** the rendered
  output (template previews and page screenshots attached to its context,
  with a self-review critique round), and compiles an automatic restorable
  snapshot per turn. Progress traces that AI runs have notes/timelines you can
  read.
- **Postings in chat** — every posting has a short ref id the chatbot
  understands: ask for open roles by board and recency, open postings by
  reference, and get "Open in Explore" deep-links from chat replies.
- **Interview prep** — posting-grounded mock interviews: question plans
  calibrated to your own skill levels from the deep posting extract (or a
  catalog archetype), coached practice with a structure/evidence/clarity
  rubric per answer, a debrief with per-dimension aggregates, learning
  resources for weak skills, and one-click weak-area retry.
- **Bring your own LLM** — any OpenAI-compatible endpoint (OpenAI, OpenRouter,
  Ollama, LM Studio). Providers, models and per-task assignments (matching,
  generation, parsing, chat…) are managed in **Settings → AI Configuration**
  — stored in the database, encrypted at rest, with no AI environment
  variables at all.
- **Dev-only mock provider** — opt-in via `MOCK_AI=1` (or
  `./scripts/run-dev.sh --mock-ai`): the deterministic mock makes everything
  work offline; without it dev AI endpoints answer 503 until a provider is
  configured, and production refuses to serve mock results (503, audited)
  regardless.
- **MCP server + client bridge** — your career data is drivable from external
  MCP clients (Claude Desktop, IDE agents): the tool registry's read-scope
  tools expose over Streamable HTTP at `/mcp` with a locally generated token
  (admin rotation), per-host rate limiting and read-only defaults; admins can
  also register external MCP servers — namespaced tools, disabled by default,
  per-tool enablement, every invocation audited and budgeted.

## Background & scheduler

- **A scheduler that works while you don't** — one engine for everything
  periodic: scheduled saved searches run on your rhythm and ping you on new
  matches, a weekly digest rolls up postings and near-misses, source syncs,
  check-ins and refit sweeps all flow through the background queue with
  jitter, misfire policies for when the desktop sleeps, and exponential
  backoff that tells you when something is stuck.
- **Desktop background mode** — close the window and the scheduler keeps
  working: the tray keeps the app alive with sync-now and saved-search
  controls, native toasts render the existing notification funnel (quiet
  hours honored, click-through deep-links, misfired runs catch up on boot), a
  single-instance lock focuses instead of double-launching, and auto-start on
  login boots tray-only.
- **Application follow-ups** — a daily sweep nudges applied postings with no
  response (+7d, +14d — adjustable), switches to congrats/check-in prompts at
  the interview/offer stages, and shows per-application follow-up state;
  delivered through the notification funnel, never double-sent.

## Taxonomy & data model (developer view)

- **Taxonomy-driven everything** — `interest_tags` and the `skills` ontology
  (key, label, category, description, subskills, 1–10 level anchors, aliases,
  proposed→active→deprecated lifecycle) plus job-family trees and work-style
  enums. Profiles, jobs and AI outputs reference stable `key` slugs, never
  labels — so labels can be renamed or translated without breaking data.
  Skills and interests link through FK join tables (`job_skills`, `job_tags`,
  `user_skills`, `user_interests`), never JSONB.
- **Structured over plain text** — everything AI produces is
  pydantic-validated into typed JSONB shapes and mapped onto the controlled
  taxonomy. Free text is allowed only as supporting `detail`.
- **Audited AI pipeline** — every AI call runs through one structured-output
  gateway, the response is validated on write, and the generation
  (task, model, tokens, output, latency) is attributed in `ai_generations`.
- **Family-compatible conventions** — same stack, settings architecture and AI
  configuration patterns as the other assistant-family apps, which keeps the
  family's knowledge model portable.

## Private by default

- **Self-hosted** — your database, your documents, your keys. Nothing phones
  home.
- **Encrypted AI keys** — provider API keys are Fernet-encrypted at rest and
  masked in every response.
- **Full AI audit trail** — every AI call (task, model, tokens, output,
  latency) is recorded in `ai_generations`.
- **Fail-safe production mode** — `APP_ENV=production` is the default; boot
  guards refuse a weak `JWT_SECRET` or `DEBUG=true`.
