<div align="center">

<img src="assets/icon-light.svg" width="120" height="120" alt="Career Assistant logo">

# Career Assistant
### AI-guided career discovery for students

[![Version](https://img.shields.io/badge/version-v0.7.1-blue.svg)](https://github.com/neuronection/career-assistant/releases)
[![Status](https://img.shields.io/badge/status-beta-yellow.svg)](#scope--limitations)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Windows%20%7C%20Docker%20%7C%20Self--Hosted-lightgrey.svg)](#quick-start)
[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat&logo=fastapi)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-20232A?style=flat&logo=react&logoColor=61DAFB)](https://react.dev/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white)](https://www.docker.com/)

  <p>
    <small>Part of</small><br>
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://neuronection.com/logos/neuronection-dark.svg">
      <img src="https://neuronection.com/logos/neuronection.svg" height="30" alt="">
    </picture>&nbsp;&nbsp;&nbsp;<picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://neuronection.com/logos/neuronection-wordmark-dark.svg">
      <img src="https://neuronection.com/logos/neuronection-wordmark.svg" height="30" alt="Neuronection — one ecosystem, four guides">
    </picture>
  </p>

**Website**: [neuronection.com](https://neuronection.com) · **Repository**: [neuronection/career-assistant](https://github.com/neuronection/career-assistant)

</div>

> **Your data stays on your own server.** Self-hosted by design — no managed cloud.

---

## Table of contents

- [What is Career Assistant?](#what-is-career-assistant)
- [What's different](#whats-different)
- [Features](#features)
- [Structured by design](#structured-by-design)
- [Quick start](#quick-start)
  - [Install from the latest release](#install-from-the-latest-release)
  - [Run from source (developers)](#run-from-source-developers)
  - [Desktop app](#desktop-app)
- [Architecture at a glance](#architecture-at-a-glance)
- [Documentation](#documentation)
- [Tech stack](#tech-stack)
- [Scope & limitations](#scope--limitations)
- [Status & roadmap](#status--roadmap)
- [Community & support](#community--support)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)
- [Disclaimer](#disclaimer)

---

## What is Career Assistant?

A self-hosted web app that helps students discover which jobs actually exist, understand which ones fit their interests, personality and constraints, and find the university pathways that lead to them — with AI woven through every step.

Under the hood it's a **structured knowledge platform**: a job catalog organized as a family tree plus a typed relation graph, deep structured student profiles, and university admissions data — all referenced by stable keys, never loose labels. AI generates jobs, suggests relations, and scores matches, but every output is validated into typed structures and audited.

It is **beta** software, built for students and technical self-hosters first.

## What's different

- **Structure over plain text.** Everything AI produces is pydantic-validated into typed JSONB shapes (`{tag_key, weight}`, `{title, detail, weight}`) and mapped onto a controlled taxonomy. Free text is allowed only as supporting `detail` — the data stays parseable and knowledge-extractable.
- **A graph, not a list.** Jobs relate through typed edges (`similar_to`, `specialises_into`, `leads_to`, `alternative_to`, `prerequisite_of`), so "what's adjacent to this?" and "what does this lead to?" are traversals, not guesswork.
- **The AI assists — it never silently decides.** Generated jobs land in a review pipeline, PDF admissions data is parsed into a reviewable draft before it touches the catalog, and every match score comes with a rationale you can read, agree or disagree with, and override with your own score.
- **Human + AI scoring.** AI scores 0–10 with positives, negatives and prerequisite checks; you score 0–10 and tag your interest status. Rankings combine both and are heavily filterable.
- **Bring your own LLM.** Any OpenAI-compatible provider works: OpenAI, OpenRouter, a local model via Ollama or LM Studio. Configured per instance, entirely through the UI.

## Features

### Explore a living job catalog

- **Family tree + relation graph** — browse job families as a tree, then follow typed relations in an interactive graph. Careers are positioned, not just listed.
- **Rich structured attributes per job** — interests, skills, work style, education, physical demands, salary bands, demand outlook, environments, typical positives and negatives.
- **AI-generated jobs** — extend the catalog with new careers; the generator maps output onto the existing taxonomy so nothing becomes an orphan of free text.
- **Search and filter** across the whole catalog.

### Build a deep, structured profile

- **Onboarding wizard** walks you through interests, skills, work-style preferences, education and constraints.
- **Start paths** — pick why you're here (explore careers, target a known job, start from your CV, or just browse) and answer only what your path needs.
- **Start from your CV** — upload an existing CV (PDF, text or photo); the intake pipeline reads it and you review what gets imported into your profile, from any point via **Profile → Import from CV**.
- **Everything is typed** — profile sections are structured JSONB validated against the taxonomy, so matching is computed, not vibes.
- **AI profile analysis** — get an external read on your profile and what it implies.

### Get matched, with reasons

- **Per-job match insights** — an AI score (0–10) with structured rationale: what fits (positives), what doesn't (negatives), and which prerequisites you're missing.
- **Your voice counts** — add your own score and interest status per job; AI and human scores coexist.
- **Filterable rankings** — combine AI score, your score and status, then slice by filters to get a shortlist you trust. Pick 2–4 jobs into the compare tray to see them side by side: per-dimension fit, gates, education, demand and salary (`/compare`), or ask the chatbot to compare them for you.

### Find the university pathway

- **Upload your university admission PDF** — an AI parsing pipeline extracts universities, departments and yearly admission baselines into a reviewable draft.
- **You approve every write** — review, edit, then apply. Parsed data never lands in the catalog unreviewed.
- **Job ↔ department pathways** — departments link to jobs through rich link rows (relevance, required subjects, salary band, employment rate), so "which degree leads here?" has a real answer.

### An AI assistant that helps — carefully

- **Chat grounded in the catalog** — the chatbot can search jobs, pull job details and look up your matches through tool-calling over your own data.
- **Contextual "Ask AI" buttons** — quick-assist endpoints power one-click explanations wherever they're useful in the UI.
- **Bring your own LLM** — any OpenAI-compatible endpoint. Providers, models and per-task assignments (matching, generation, parsing, chat…) are managed in **Settings → AI Configuration** — stored in the database, encrypted at rest, with no AI environment variables at all.
- **Dev-only mock provider** — development auto-provisions a deterministic mock so everything works offline; production refuses to serve mock results (503, audited).

### Private and auditable

- **Self-hosted** — your database, your documents, your keys. Nothing phones home.
- **Encrypted AI keys** — provider API keys are Fernet-encrypted at rest and masked in every response.
- **Full AI audit trail** — every AI call (task, model, tokens, output, latency) is recorded in `ai_generations`.
- **Fail-safe production mode** — `APP_ENV=production` is the default; boot guards refuse a weak `JWT_SECRET` or `DEBUG=true`.

## Structured by design

Career Assistant is a student tool today, but the foundation is the same one the rest of the assistant family uses, so the same installation can grow into richer domain features — or share knowledge with its siblings — without a rewrite. You don't need to care about any of this for everyday use; it's here for when you do.

- **Taxonomy-driven everything** — `interest_tags` and the `skills` ontology (key, label, category, description, subskills, 1–10 level anchors, aliases, proposed→active→deprecated lifecycle) plus job-family trees and work-style enums. Profiles, jobs and AI outputs reference stable `key` slugs, never labels — so labels can be renamed or translated without breaking data. Skills and interests are linked through FK join tables (`job_skills`, `job_tags`, `user_skills`, `user_interests`), never JSONB.
- **Career paths as data** — curated and AI-drafted routes to each job, with a computed graph of "jobs that lead here" over the typed relation edges.
- **Deterministic fit engine** — every job gets a transparent 0–10 fit score with a per-dimension breakdown (skills, education, experience, location, interests + work style, work values) you can inspect and re-weight; interest scoring blends tag overlap with RIASEC affinity vectors derived from your interest tags, work values are scored against a job's derived signal (benefit kinds included), and hard-constraint gates move jobs to a "Stretch goals" view with explanations instead of deleting them; no popularity or demand term ever touches the score.
- **JobTypeMatch assessment** — a 4-phase profiling pipeline (profile foundation, standardized scenarios, AI-generated scenarios, personalized selection) with resumable runs, custom re-runs, and evidence reconciliation: scenario answers refine your skill levels while large conflicts with your self-rating are flagged, never silently overwritten.
- **Engagement loop** — a discovery feed ordered unseen-first by fit (with an exploration slot for families you haven't seen), search history with one-click re-runs and saved searches, bookmarks and feed hiding that never touch your semantic job status, curated https-only application links beside the education requirement, and threshold alerts (fit ≥ your line, or new jobs in families you follow) with per-day caps, cooldowns and a kind registry — the substrate's multi-channel notification center builds on.
- **Career stages, not just students** — one switch (student, early career, experienced, switching, returning — derived when unset, always correctable) retunes your suggested fit weights, asks assessment scenarios grounded in your stage, reorders career paths experience-first, and gates student-only modules like university intake behind feature flags. The engine stays one engine: presets are suggestions, never hidden scoring branches.
- **A scheduler that works while you don't** — one engine for everything periodic: scheduled saved searches run on your rhythm and ping you on new matches, a weekly digest rolls up postings and near-misses, source syncs, check-ins and refit sweeps all flow through the background queue with jitter, misfire policies for when the desktop sleeps, and exponential backoff that tells you when something is stuck.
- **Background mode for the desktop app** — close the window and the scheduler keeps working: the tray keeps the app alive with sync-now and saved-search controls, native toasts render the existing notification funnel (quiet hours honored, click-through deep-links, misfired runs catch up on boot), a single-instance lock focuses instead of double-launching, and auto-start on login boots tray-only.
- **Growth toolkit** — the product works after you're hired: roadmaps turn skill gaps into tracked steps (done → level self-report → catalog re-fit, visibly), a near-miss radar shows adjacent roles you're a couple of skills away from, learning resources close the gaps, market snapshots aggregate live postings per role (honest thin-sample handling), quarterly check-ins and per-rule quiet hours keep it useful and discreet.
- **Express start & target mode** — already know the job you want? Type it, pick your targets, answer two questions — live postings, alerts and suggestions start immediately, with a target-mode dashboard (open jobs, salary band, top employers, adjacent careers) and a completeness ring that shows exactly which 5-minute step sharpens your results next. No profiling marathon unless you want it.
- **Live postings, legally** — a connector SDK ships first-party engines for what's free and legal (ATS public APIs, schema.org JSON-LD, RSS, CSV, paste-a-URL) and lets anyone add more as plugins (admin-opt-in). Postings map onto the catalog by literal skill-ID intersection — never label matching — inherit your fit score with freshness/remote/seniority adjustments (no per-posting AI), flow through the same seen/saved/alerts machinery as the catalog, and track your saved→applied funnel.
- **Deep extraction & skill-level search** — a queued LLM pass turns postings into auditable data: skills with required level 1–10 and priority, each backed by a verbatim evidence quote, plus salary, responsibilities with time splits and seniority — low-confidence fields are suppressed for review, never guessed. Extraction v2 adds contract type, work hours, schedule cues, travel demand, onsite policy and typed benefits (each with its own evidence), and your lifestyle constraints gate postings — flagged on the card, never hidden. Search vacancies by "skill X at level ≥ N", rank them by deterministic coverage of your skills, and read the provenance (raw → fast-mapped → extracted) on every card.
- **Explore, per-posting match & chat** — the Explore page filters every structured field (including contract type, travel, schedule cues, benefits and organization) with live facet counts, saves searches you can schedule, and paginates by cursor; posting detail shows a per-posting match score built from the extracted data (weighted by your fit sliders, stale-proof), source attribution and similar roles; every posting has a short ref id the chatbot understands — ask for open roles by board and recency, open postings by reference, and get "Open in Explore" deep-links from chat replies.
- **Career Autopilot** — describe a goal once ("junior QA role, remote, €30k+") and an agent searches your connected boards on a cadence or on demand: it plans multiple query/filter variants, filters noise (seen/applied, never-terms, a per-goal cooldown), ranks by your deterministic fit score, and delivers a curated shortlist where every explanation cites verbatim quotes verified against the posting's own text. A "what I searched & why" timeline shows each run's work; budgets hard-cap runs (partials still ship); "more/hide like this" teaches the goal's constraints, dismissing a whole shortlist pauses it, and three empty runs trigger a refine-the-goal nudge — never wasted spend, never auto-applying.
- **Typed relation graph** — job relations carry weight, rationale and source; the graph is first-class data, not UI decoration.
- **Rich university link model** — per-year admissions rows and job↔department links with relevance, required subjects, salary band and employment rate.
- **Audited AI pipeline** — every structured output is pydantic-validated on write and attributed in `ai_generations`; invalid AI output never lands in the database.
- **CV Studio** — upload a CV (byte-preserved original, OCR text layer) or start from scratch, build it block-by-block against a per-CV context selection you control (every rendered line traces to a profile item), pick from versioned templates with a deterministic renderer, get grounded AI writing help (summaries, bullet rewrites, tailoring with must-have coverage), and draft **cover letters per posting** from a structured brief — every paragraph cites your evidence, unbacked claims are flagged before they can be applied. An **Ask AI copilot side panel** operates the builder for you: templates, themes/styling, context selection, sections, per-item rewrites and document options — applied as validated operations, self-reviewed against rendered page screenshots, with an automatic restorable snapshot per turn. Exports to PDF/DOCX/Markdown/JSON/ATS text.
- **One metric language** — beyond skills, a dimension registry (RIASEC interest affinities, work values, work style) stores what assessments, profile sections and behavior measure, with provenance; the fit engine, filters and weight sliders all speak it, and skill transferability ("your SQL transfers to 12 of 20 families") derives from the catalog join graph.
- **Organizations are entities, not labels** — postings resolve onto a normalized organization through a matcher that folds legal-suffix and spelling variants into aliases; duplicates merge under admin review, and "top hiring orgs" aggregates by entity, never by label matching.
- **Family-compatible conventions** — same stack, settings architecture and AI configuration patterns as Health Assistant, which keeps the family's knowledge model portable.

## Quick start

### Install from the latest release

Linux installers (`.deb` / `.AppImage`) and the Windows executable are
published on the [Releases page](https://github.com/neuronection/career-assistant/releases).

### Run from source (developers)

From a fresh clone to a running instance:

```bash
git clone https://github.com/neuronection/career-assistant.git
```

```bash
cd career-assistant
```

```bash
cp .env.example .env                                # defaults work out of the box
docker compose -f docker/docker-compose.dev-db.yml up -d   # Postgres :5433 + Redis :6380
./scripts/run-dev.sh                                # backend :8100 + frontend :3100
```

Seed the starter catalog (46 interests, 32 skills, 45 jobs, 34 relations — idempotent):

```bash
./scripts/seed.sh
```

Open **http://localhost:3100**, register, complete the onboarding wizard, then explore the catalog, generate jobs with AI and score your matches. Interactive API docs: **http://localhost:8100/docs**.

### Desktop app

Run it as a local desktop application (pywebview window, SQLite database, everything under your OS data dir — no Docker, no Postgres):

```bash
cd backend
python -m venv venv && ./venv/bin/pip install -r requirements-desktop.txt
./venv/bin/python -m careerassistant              # window + tray (default mode)
./venv/bin/python -m careerassistant app --tray   # tray-only boot (auto-start)
./venv/bin/python -m careerassistant web          # loopback server + system browser
./venv/bin/python -m careerassistant seed         # migrations + starter catalog only
```

**Prebuilt packages** (no Python needed) are published on the
[Releases](https://github.com/neuronection/career-assistant/releases) page
for every tagged version: `.deb` + AppImage (Linux) and a portable
`CareerAssistant-windows-x64.exe` (Windows).

Closing the window keeps the app running in the tray (after a first-run
opt-in prompt) — scheduled searches, syncs and alerts continue in the
background, native toasts arrive through the desktop notification
channel, and quitting happens from the tray menu. A second launch focuses
the running window; auto-start on login is opt-in from the tray menu.

First launch creates a strong `secret.key`, applies migrations and seeds the starter catalog automatically (opt out with `CAREER_SKIP_SEED=1`). AI providers are configured in-app (Settings → AI Configuration) — for a fully local setup point a provider at Ollama (`http://localhost:11434/v1`) or LM Studio. Linux needs `libgtk-3`, `libwebkit2gtk-4.1` and an AppIndicator host (tray degrades gracefully without one).

### Prerequisites

- **Docker** and Docker Compose (for the dev database), or **Python 3.12+ / Node 18+** for the app itself.
- **An OpenAI-compatible LLM provider** (API key + endpoint) for job generation, relation suggestion, matching, PDF parsing and the chatbot. Configure it in **Settings → AI Configuration**. In development a built-in mock provider is auto-provisioned, so the app works fully without one.
- **PostgreSQL** — the dev compose ships one on port 5433; Redis (6380) is included for a future worker split.

## Architecture at a glance

```mermaid
flowchart LR
    subgraph Clients
        FE[React SPA<br/>Vite + Zustand + reactflow]
    end
    subgraph Server["FastAPI server"]
        API[REST API<br/>JWT bearer auth]
        BG[Background tasks<br/>PDF parsing · AI generation]
    end
    subgraph Datastore
        PG[(PostgreSQL<br/>typed columns + JSONB)]
        RQ[(Redis<br/>future worker queue)]
    end
    LLM[Your LLM<br/>OpenAI-compatible]
    AG[AI agents<br/>generate · relate · score · parse · chat]

    FE --> API
    API <--> PG
    API --> BG
    BG <--> PG
    API <--> RQ
    AG <--> API
    AG --> LLM
```

The frontend talks to **domain endpoints** optimized for the UI: catalog (tree + graph), profile, matching, universities, chat and AI settings. All AI work runs through a single structured-output pipeline (`ainvoke_structured`): the resolved provider/model is called, the response is pydantic-validated, and the generation is audited — there is no side door around it.

PDF parsing and AI generation run as FastAPI background tasks; Redis ships in the compose file for a later worker split (no Celery in v1). Deep dive: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Documentation

**Getting started**
- [Architecture](docs/ARCHITECTURE.md) — modes, runtime topology, registries, AI pipeline
- [Deployment](docs/deploy.md) — self-hosting with the production compose stack, TLS, upgrades, backups
- [Contributing](CONTRIBUTING.md) — dev setup, conventions, PR checklist
**Core systems** (deep dives in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md))
- Catalog & Taxonomy — job families, structured attributes, typed relations
- AI System — provider registry, agents, audit trail
- Universities & PDF intake — parse → review → apply pipeline
- Matching & Rankings — AI + human scoring, filters
- Chat & Ask AI — tool-calling chatbot, quick-assist

**Project status**
- [Changelog](CHANGELOG.md) — notable changes per release

Interactive API docs are also available at `/docs` on a running backend.

## Tech stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (Python 3.12+), async, SQLAlchemy 2.0 (`asyncpg`), Pydantic v2 |
| Frontend | React 18 + Vite + TypeScript (strict) + Tailwind |
| State | Zustand |
| Database | PostgreSQL (web/self-host, typed columns + JSONB) · SQLite (desktop profile) — one portable schema |
| Cache / Queue | Redis (composed in; worker split planned) |
| Migrations | Alembic |
| AI / NLP | OpenAI-compatible providers (`openai` SDK, `base_url` override → OpenAI / OpenRouter / Ollama / LM Studio), pydantic-validated structured outputs, deterministic dev-only mock |
| Auth | JWT bearer (PyJWT) + bcrypt |
| Graph / Charts | reactflow (job graph), recharts (rankings) |
| Tests | pytest + pytest-asyncio + httpx, vitest + testing-library, ruff |
| Container | Docker + Docker Compose (dev database) |

## Scope & limitations

Career Assistant is in **public beta** (`0.7.x`). The points below are honest boundaries — not every limitation is a bug.

- **Pre-1.0 APIs.** REST endpoints and DB schemas may change before `1.0`. Pin a version if you depend on it.
- **Single-container scale.** One uvicorn process serves the API and the built SPA (see [Deployment](docs/deploy.md)); there is no horizontal-scaling story yet. A worker split is on the roadmap.
- **No Celery in v1.** PDF parsing and AI generation run as in-process FastAPI background tasks. Redis ships in the compose file for a later worker split; today the FastAPI process does the work itself.
- **Single-tenant.** Students are `users`; there is no tenancy model. Multi-school/organization support is not on the v1 roadmap.
- **AI features need a configured provider in production.** A fresh production install starts unconfigured and AI endpoints answer 503 until an admin sets a provider up in the UI. The mock provider can never serve results in production.
- **Test coverage.** The backend has a solid pytest suite and the frontend has vitest coverage, but there is no end-to-end suite yet.
- **University intake is manual-review.** PDF parsing extracts a draft; it is not an official data feed and should always be reviewed against the source document.
- **No career-counseling certification.** This software is informational; it does not replace professional career or academic guidance (see [Disclaimer](#disclaimer)).

## Status & roadmap

**Recently shipped** — see [CHANGELOG.md](CHANGELOG.md) for the full story:

- **Discovery wave** — skill ontology (21), deterministic fit engine (22), JobTypeMatch assessment (23), engagement & notifications (24: search history, feed, alerts), career stages (25).
- **Live postings wave** — connector SDK with ATS/JSON-LD/RSS/CSV/URL engines, skill-ID mapping, applications tracking (26), express start & target mode (27), growth toolkit (roadmaps, near-miss radar, market snapshots, check-ins) (28), the modular scheduler feeding the background queue — scheduled searches, weekly digests, syncs, refit sweeps (29).
- **Desktop background mode** — tray + close-to-tray, single-instance, auto-start, native notifications off the notification funnel.
- **Deep posting extraction** — skills with levels + evidence quotes, salary, responsibilities; skill-level search and profile-coverage ranking.
- **Postings Explore & chat tools** — full filter+facet Explore page, per-posting match scores, short ref ids, chatbot posting tools.
- **CV Studio foundation** — upload a CV with the original preserved byte-for-byte, text-layer + OCR text extraction with derived page images, and versioned CV records (immutable snapshots, canonical hashes) behind the new `/cv` API.
- **CV intake** — automatic AI field extraction into a review-first draft: every item carries an evidence quote and confidence, apply writes only what you confirm (experience, skills with evidence, education, certifications, awards, contact), and re-uploading a CV dedupes instead of duplicating.
- **CV templates** — five seeded starter layouts, versioned template packages (blocks, design tokens, page rules, per-field AI prompts), one deterministic renderer, AI template drafts and a visual-review loop (layout lint + vision critique of printed scans), hash-verified file-first import/export.
- **CV Studio waves** — the builder: per-CV context selection, live preview with page meter, versions with diff/restore, exports everywhere, ATS lint; structured profile forms with the experience workspace (master-detail, optimistic delete with undo); the three-pane workspace UI with command palette, undo/redo and AI proposal review.
- **CV builder copilot** — the docked "Ask AI" side panel in the builder: the model returns a bounded structured operation plan (template, theme/design tokens with bank-template auto-customization, context selection, block add/remove/move/configure, per-item text overrides, document options), the backend applies it through the same services the UI uses, optionally screenshots the rendered pages for a vision critique with one refine round, and every mutating turn compiles a restorable `ai_apply` snapshot.
- **Interview prep** — posting-grounded mock interviews: question plans calibrated to your own skill levels from the deep posting extract (or a catalog archetype), coached practice in the shared chatbot with a structure/evidence/clarity rubric per answer, a debrief with per-dimension aggregates, learning resources for weak skills, and one-click weak-area retry.
- **Application follow-ups** — a daily sweep nudges applied postings with no response (+7d, +14d — adjustable), switches to congrats/check-in prompts at the interview/offer stages, and shows per-application follow-up state; delivered through the notification funnel, never double-sent.
- **MCP server + client bridge** — your career data is drivable from external MCP clients (Claude Desktop, IDE agents): the tool registry's read-scope tools expose over Streamable HTTP at `/mcp` with a locally generated token (admin rotation), per-host rate limiting and read-only defaults; admins can also register external MCP servers — namespaced tools, disabled by default, per-tool enablement, every invocation audited and budgeted.
- **Semantic search & skill packs** — postings embed into a portable vector store (pgvector optional, plain Postgres/SQLite fully supported); Explore's relevance search fuses lexical and semantic rankings without ever bypassing your hard filters; task-steering AI instructions ship as versioned, audited skill packs.
- **Metric model residuals** — opt-in revealed preferences (engagement nudges your RIASEC vector by ≤5%/week, never the exploration slot), an application outcome funnel per family (observation only — never scored), engine dimension lists from one spec, and RIASEC/values bank batteries in the assessment template library.
- **Cover letters** — per-posting letters with a deterministic brief (must-haves, fit, your goal), audited AI drafts that cite your evidence per paragraph, letter rendering through the same template engine, and the same versions/exports as CVs.
- **Metric model** — dimension registry + per-user metric profile; RIASEC interest affinities, work-values fit dimension (job signal from structured attributes + benefit kinds), lifestyle constraints with a salary-minimum gate, and per-skill transferability across job families.
- **Extraction v2 & catalog parity** — contract/hours/schedule/travel/onsite + typed benefits with evidence; the feature map that binds extracted fields to consumers and generates the extraction prompt; normalized organizations with a dedup matcher, admin merge and org-aware market snapshots; a moderation-reviewed enrichment sweep that brings catalog archetypes to the same vocabulary; Explore filters for all of it.
- **Earlier** — production self-host stack, desktop app (`python -m careerassistant`, SQLite local profile, pywebview shell), Linux packaging (`.deb` + `.AppImage` via CI) — see [docs/deploy.md](docs/deploy.md).

**Up next**:

- Notification-center library unification and health-assistant adoption — shared work in the assistant-ui and health repos.
- Pending rescope: match staleness/bulk re-score, E2E + typing gates, broader i18n coverage, demand-history trends; sustainability model.

## Community & support

Questions: [Discord](https://discord.com/invite/SZCXNTwv) ·
Bugs & feature requests: [Issues](https://github.com/neuronection/career-assistant/issues) ·
Support development: [Buy Me a Coffee](https://buymeacoffee.com/neuronection)

## Contributing

Contributions are welcome. To set up a working dev environment, follow [Quick start](#quick-start) and read [CONTRIBUTING.md](CONTRIBUTING.md) for code style, testing and the PR checklist.

For backend changes, run `ruff check` / `ruff format --check` and the pytest suite before submitting. For frontend changes, `npm run build`, `npm run test -- --run` and `npm run lint` must pass. Security issues go through [SECURITY.md](SECURITY.md), never public issues.

## Security

Found a vulnerability? Do not open a public issue — see
[SECURITY.md](SECURITY.md) for the private disclosure process.

<!-- NEURONECTION:ECOSYSTEM:START -->
---

<div align="center">

### Part of the Neuronection family

**Career Assistant** is one of four connected, open-source (Apache-2.0) AI assistants
for life's big decisions — structured data instead of text dumps, AI that explains
its reasoning, and you in control of your information.

<table>
  <tr>
    <td width="50%" align="center" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="https://neuronection.com/logos/health-light.svg">
        <img src="https://neuronection.com/logos/health.svg" height="34" alt="Health Assistant">
      </picture>
      <br>
      <a href="https://neuronection.com/en/health/"><strong>Health Assistant</strong></a>
      <br><sub>Self-hosted, privacy-first health records — lab results, biomarkers, documents and AI-powered insights into your own data.</sub>
      <br><sub><a href="https://github.com/health-assistant-io/health-assistant">GitHub</a> · <a href="https://health-assistant.io">health-assistant.io</a></sub>
    </td>
    <td width="50%" align="center" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="https://neuronection.com/logos/career-light.svg">
        <img src="https://neuronection.com/logos/career.svg" height="34" alt="Career Assistant">
      </picture>
      <br>
      <a href="https://neuronection.com/en/career/"><strong>Career Assistant</strong> <sub>· this repo</sub></a>
      <br><sub>A mapped universe of jobs — family tree + relation graph, AI match scoring and university pathways, built for students deciding their future.</sub>
      <br><sub><a href="https://github.com/neuronection/career-assistant">GitHub</a> · <a href="https://github.com/neuronection/career-assistant/tree/main/docs">Docs</a></sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center" valign="top">
      <img src="https://neuronection.com/logos/study.svg" height="34" alt="Study Assistant">
      <br>
      <a href="https://neuronection.com/en/study/"><strong>Study Assistant</strong></a>
      <br><sub>A local-first study workbench, in browser or on desktop — AI-powered course library, handwriting, chat and practice; math-first, subject-agnostic.</sub>
      <br><sub><a href="https://github.com/neuronection/study-assistant">GitHub</a> · <a href="https://github.com/neuronection/study-assistant/tree/main/docs">Docs</a></sub>
    </td>
    <td width="50%" align="center" valign="top">
      <img src="https://neuronection.com/logos/desktop.svg" height="34" alt="Desktop Assistant">
      <br>
      <a href="https://neuronection.com/en/desktop/"><strong>Desktop Assistant</strong></a>
      <br><sub>A system-tray AI launcher for Windows, Linux and macOS — global hotkey, streaming chat, voice input, attachments; local-only history.</sub>
      <br><sub><a href="https://github.com/neuronection/desktop-assistant">GitHub</a> · <a href="https://github.com/neuronection/desktop-assistant/tree/main/docs">Docs</a></sub>
    </td>
  </tr>
</table>

Created and maintained by [Ilias Chatzopoulos](https://github.com/constLiakos)
· [LinkedIn](https://www.linkedin.com/in/ilias-chatzopoulos-aabb22163/)
· [info@neuronection.com](mailto:info@neuronection.com)

[neuronection.com](https://neuronection.com) — one ecosystem, four guides
· [♥ Support development](https://buymeacoffee.com/neuronection) · star what you use

</div>
<!-- NEURONECTION:ECOSYSTEM:END -->

## License

Apache License 2.0 — see [LICENSE](LICENSE). © 2026 constLiakos.

## Disclaimer

This software, including its AI chatbot and agentic features that may offer career-related information, guidance, or job and education explanations, is for informational purposes only. It does **not** provide professional career counseling and is not a substitute for qualified academic advisors, career counselors, or official university admissions offices. Always verify admission baselines and program requirements against official sources before making education or career decisions based on the software's output.
