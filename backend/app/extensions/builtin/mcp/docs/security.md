# Security

## The perimeter, stated plainly

> This extension runs as a separate process outside the app's network perimeter. It opens its own network connections, with no SSRF guard, robots.txt check or rate limiting by the app. The app governs only what it returns: outputs are validated and capped.

That is the family's Tier-3 disclosure, rendered verbatim from the
extension charter — read it before adding a source, and again whenever
a source's server changes. The connector's manifest deliberately
declares **no** `net` capability: the script's own sockets are outside
the host perimeter, disclosed here instead of smuggled in as a
capability.

## What the app governs

- **Row validation + caps** — every returned row is validated against
  the postings contract before it enters your data; malformed rows are
  typed errors, never silently dropped or coerced.
- **One audit row per tool call** — tool name, arguments (with secret
  values stripped), latency, outcome.
- **Tool allowlist + timeout** — enforced per call, not per promise.
- **Secret sealing** — the optional bearer token lives sealed at rest;
  it is injected at call time and never crosses into stored config.

## What only you can govern

- **The server's own behavior** — what it fetches, where it sends
  data, how it authenticates. Run servers you trust, from sources you
  can read; the template repo is the family's reference scaffold.
- **The service user's filesystem reach** — the spawned process runs
  with the app service user's permissions; sandbox it at the OS level
  if the source is untrusted.
- **Updates to the server code** — re-read the disclosure above
  whenever the script changes; the app cannot detect that it changed.
