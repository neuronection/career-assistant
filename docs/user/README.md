# Career Assistant — user guide

Career Assistant is a self-hosted app that helps you navigate career
decisions: discover which jobs exist, understand which fit your interests,
personality and constraints, find the education pathways that lead to them,
search live job postings, and build a CV — with AI woven through every step
but never deciding for you.

Your data stays on your own server (or your own machine, in the desktop
app). The only traffic that leaves is the AI calls you configure yourself.

New here? Read **[Getting started](getting-started.md)** first, then follow
the tour below. For the exhaustive list of everything the app does, see the
**[feature catalog](features.md)**.

## Guides

| Guide | What you will learn |
|---|---|
| [Getting started](getting-started.md) | Install (desktop, Docker or bare metal), connect an AI provider, first steps |
| [Onboarding and your profile](onboarding-and-profile.md) | The wizard and start paths, every profile section, importing an existing CV |
| [Feature catalog](features.md) | Everything, as built — the reference tour |
| [Explore the job catalog](explore-the-catalog.md) | Job family tree, typed relation graph, rich job detail, AI-generated jobs |
| [Matching and rankings](matching-and-rankings.md) | AI scores with rationale, your own scores, the fit engine, rankings and compare |
| [Universities and pathways](universities.md) | Admission-PDF intake, reviewable drafts, degree-to-job pathways |
| [Assessment and metrics](assessment.md) | The JobTypeMatch assessment, the metric model, career stages |
| [Postings and search](postings-and-search.md) | Connectors, live postings, deep extraction, the Explore page |
| [Career Autopilot](career-autopilot.md) | Goal-driven agent searches with budgets and explainable shortlists |
| [Growth toolkit](growth.md) | Roadmaps, near-miss radar, market snapshots, check-ins |
| [CV Studio overview](cv-studio.md) | Three ways to a CV, the builder, context, versions and exports |
| [Templates and design](cv-design-and-templates.md) | Template bank, the design-token editor and visual review |
| [Variant library](cv-variants.md) | AI and manual item variants, bullets, staleness and pins |
| [Cover letters](cover-letters.md) | Per-posting cover letters and their evidence trail |
| [Chat and proposals](assistant-chat.md) | The assistant, review-card profile edits, the builder copilot, MCP |
| [Interview prep](interviews.md) | Posting-grounded mock interviews and coached practice |
| [Notifications and scheduler](notifications-and-scheduler.md) | Alerts, digests, quiet hours and the periodic engine |
| [Desktop app](desktop-app.md) | The window, the tray, background scheduling and auto-start |
| [Settings reference](settings.md) | Every settings page explained |
| [Privacy and security](privacy-and-security.md) | Where your data lives and how it is protected |
| [Troubleshooting](troubleshooting.md) | Common problems and fixes |

## The five-minute version

1. **Install** the desktop app from the
   [Releases](https://github.com/neuronection/career-assistant/releases)
   page, or run the self-hosted stack with Docker.
2. **Connect an AI provider** in **Settings → AI Configuration** — any
   OpenAI-compatible endpoint (OpenAI, OpenRouter, or a local Ollama/LM
   Studio). The app starts unconfigured and AI features answer `503` until
   you do.
3. **Onboard** — pick why you are here (explore, target a known job, start
   from your CV, or browse) and answer only what your path needs.
4. **Explore** the catalog, **get matched** with reasons, then **search live
   postings** and let **Career Autopilot** hunt a goal on a cadence.
5. When you are ready, build a CV in **CV Studio** — from a template, from
   your existing CV, or on demand from your profile.

## Where to get help

- Bugs and feature requests:
  [GitHub Issues](https://github.com/neuronection/career-assistant/issues)
- Questions: [Discord](https://discord.com/invite/SZCXNTwv)
- Project status and known limitations: [STATUS.md](../STATUS.md)
- Developers and self-hosters: [developer guide](../dev/README.md)
