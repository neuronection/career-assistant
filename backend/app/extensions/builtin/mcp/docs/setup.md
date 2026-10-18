# Setup

## 1. Allowlist the connector (admin)

The MCP source is allowlist-gated: it does not appear in the connector
list until `connector_plugins_allowlist` names it (`mcp`). An admin
sets this in the deployment settings — it is deliberately not a
self-service toggle.

## 2. Run (or reach) a server

Two transports:

- **stdio** — the app spawns the server from a command line you
  configure (e.g. `python server.py` in the template repo). Use an
  absolute command; the process runs under the app's service user.
- **http** — the app connects to a running endpoint URL. Optionally
  protect it with a bearer token (the token is a declared secret
  slot: it lives sealed in the source's secret store, never in
  config).

## 3. Add the source

1. Settings → Tools → Connectors → **Add source** → MCP script.
2. Configure: transport (`stdio`/`http`), command or URL, the **fetch
   tool** name (default `fetch_postings`), an optional **tool
   allowlist** (comma-separated; empty = just the fetch tool), and a
   **timeout** (5–120 s, default 30).
3. Save and sync. The first sync spawns/connects, calls the fetch
   tool, and validates the returned envelope.

## What to be careful at

- **Tool allowlist is per source** — name exactly the tools you expect
  the source to use; the connector refuses unnamed tools.
- **Timeouts** — a slow board should get a bigger timeout, not
  retries; each call is audited and rate-capped by its own config.
