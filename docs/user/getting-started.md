# Getting started

Career Assistant runs in two ways, both first-class:

- **Desktop app** — a local window (pywebview) with a system tray, a SQLite
  database and everything under your OS data directory. No Docker, no
  Postgres, no browser needed.
- **Web / self-hosted** — one container (or one uvicorn process) serving the
  API and the built web app, backed by PostgreSQL. Reach it from any browser.

This page covers both. If you just want to try it, the desktop app is the
fastest path. If you are deploying for others, see
[Deployment](../dev/deployment.md) instead.

## Prerequisites

- **Desktop:** a prebuilt package needs nothing installed; running from
  source needs **Python 3.12+**.
- **Self-hosted:** **Docker** + Docker Compose, or **Python 3.12+** and
  **Node 20+** for a bare-metal install.
- **An OpenAI-compatible LLM provider** (API key + endpoint) for AI
  features. Configure it in the app after first launch — there are no AI
  environment variables. For offline development you can opt into the
  built-in mock provider.

## Install the desktop app

Download the installer for your platform from the
[Releases](https://github.com/neuronection/career-assistant/releases) page:

| Platform | File |
|---|---|
| Windows | `CareerAssistant-windows-x64.exe` (portable) |
| Linux (AppImage) | `CareerAssistant-x86_64.AppImage` |
| Linux (deb) | `careerassistant_amd64.deb` |

Linux needs `libgtk-3`, `libwebkit2gtk-4.1` and an AppIndicator host (the
tray degrades gracefully without one).

### Run the desktop app from source

```bash
cd backend
python -m venv venv && ./venv/bin/pip install -r requirements-desktop.txt
./venv/bin/python -m careerassistant              # window + tray (default)
./venv/bin/python -m careerassistant app --tray   # tray-only boot (auto-start)
./venv/bin/python -m careerassistant web          # loopback server + browser
./venv/bin/python -m careerassistant seed         # migrations + starter catalog only
```

First launch creates a strong `secret.key`, applies migrations and seeds the
starter catalog automatically (opt out with `CAREER_SKIP_SEED=1`). Closing
the window keeps the app running in the tray after a first-run opt-in prompt
— see [Desktop app](desktop-app.md).

## Install the self-hosted stack

```bash
git clone https://github.com/neuronection/career-assistant.git
cd career-assistant

cp docker/.env.production.example docker/.env
# Edit docker/.env — set JWT_SECRET and POSTGRES_PASSWORD (long random values)

docker compose -f docker/docker-compose.prod.yml up -d --build
```

The app is on `http://<host>:8100`. Migrations run automatically on every
start. For a single-host stack with bundled nginx (TLS-ready) use
`docker/docker-compose.standalone.yml` instead. First-time deploys can also
use `./scripts/run-docker.sh`; existing installs refresh via
`./scripts/update-docker.sh`.

By default the app runs in **single-user mode**: a single default user
(instance admin) is created automatically, and you are never asked to log
in or register. To run a classic multi-user instance instead, set
`SINGLE_USER_MODE=false` in `docker/.env` and register the first user
through the app (it automatically becomes the admin).

See [Deployment](../dev/deployment.md) for the full configuration reference,
TLS, upgrades, backups and bare-metal installs.

## Connect an AI provider

AI features are unconfigured on a fresh install. Open
**Settings → AI Configuration** and add a provider:

1. Pick a provider (OpenAI, OpenRouter, or any OpenAI-compatible endpoint —
   for a fully local setup point it at Ollama `http://localhost:11434/v1` or
   LM Studio).
2. Paste the API key. Keys are encrypted at rest and masked in every
   response.
3. Choose models and assign them to tasks (matching, generation, parsing,
   chat…). Assignments can differ per task.

Until a provider is configured, AI endpoints answer `503`. In development
you can instead start the backend with the built-in mock provider
(`./scripts/run-dev.sh --mock-ai` or `MOCK_AI=1`) so everything works
offline — the mock can never serve results in production.

## Your first session

1. **Onboard.** The wizard walks you through interests, skills, work-style
   preferences, education and constraints — or pick a **start path** (explore
   careers, target a known job, start from your CV, or just browse) and
   answer only what your path needs. See
   [Onboarding and your profile](onboarding-and-profile.md).
2. **Explore the catalog.** Browse job families as a tree, then follow typed
   relations in the graph. See
   [Explore the job catalog](explore-the-catalog.md).
3. **Get matched.** Score jobs with AI and with your own score, then filter
   the rankings. See
   [Matching and rankings](matching-and-rankings.md).
4. **Search live postings.** Connect a board, then filter and save searches
   on the Explore page. See
   [Postings and search](postings-and-search.md).
5. **Build a CV.** When you are ready, open CV Studio. See
   [CV Studio overview](cv-studio.md).

## Where your data lives

- **Desktop:** under your OS data directory — the SQLite database, uploads,
  `secret.key` and the checkpointer database. Nothing is sent anywhere
  except the AI calls you configure.
- **Self-hosted:** the Postgres volume (`db_data`) and the uploads volume
  (`uploads_data`). Back them up — see
  [Deployment](../dev/deployment.md#backups).

Read [Privacy and security](privacy-and-security.md) for the full picture.

## Next

- [Onboarding and your profile](onboarding-and-profile.md)
- [Feature catalog](features.md)
- [Troubleshooting](troubleshooting.md)
