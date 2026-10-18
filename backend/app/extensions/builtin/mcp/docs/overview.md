# MCP script (external process)

The MCP connector ingests job postings from an external MCP server you
run yourself — Tier 3 in the family's extension ladder: an
out-of-process script the app spawns (stdio) or connects to (http),
never code loaded into the app.

- **You choose the server.** Any MCP server that answers a fetch tool
  with the app's postings envelope (the
  `career-connector-template` repo is the authoring scaffold).
- **Admin-gated.** The connector is invisible until an admin
  allowlists it — off by default, structurally.
- **Governed on the way back.** The app validates and caps every row
  the server returns; one audit row records each tool call.

## When to use it

A postings source the bundled set does not cover — a private board, an
internal ATS gateway, a scraping service you trust — that you can run
as a process you control.

## When NOT to use it

Anything the bundled connectors already cover (CSV, JSON-LD, RSS, ATS
APIs, the three job boards): those run in-process, inside the app's
SSRF/robots/rate perimeter, with no external process to operate. If
you are not comfortable operating a script, this is not your source.
