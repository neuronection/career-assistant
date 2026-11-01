# Remotive remote jobs

A bundled connector that syncs job postings from Remotive's public
remote-jobs RSS feed (`remotive.com/remote-jobs/feed`) — free, no
credentials (no secret slots by design). The feed is the endpoint
Remotive's robots.txt allows: their JSON API sits behind
`Disallow: /api/*`, so this connector never touches it.

- **Remote-first board.** Every row is a remote position; the geo
  restriction rides the row's location note, not a config flag.
- **Category filter.** Remotive categorizes postings (Software
  Development, Design, …); the connector keeps the rows whose category
  matches the configured value (case-insensitive) — filtering happens
  client-side because robots disallows `category=` query params. Add two
  instances for two categories.
- **Full descriptions.** Feed items carry the complete HTML description,
  so skills extraction runs on first ingest — no detail pass needed.
- **Attribution.** Remotive's legal notice asks for attribution and a
  link back — the posting URL IS the `remotive.com` URL, so
  attribution rides the data itself.

## When to use it

Remote-only searches across many companies, refreshed on your sync
schedule, with zero setup.

## When NOT to use it

On-site/hybrid searches in a specific city (use Arbeitnow for
German/European boards or an ATS/URL source for a target employer), or
when you need salary bands — Remotive rows rarely carry them.
