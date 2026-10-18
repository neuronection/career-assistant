# Remotive remote jobs

A bundled connector that syncs job postings from Remotive's public
remote-jobs API — free, no credentials (no secret slots by design).

- **Remote-first board.** Every row is a remote position; the geo
  restriction rides the row's location note, not a config flag.
- **Category filter.** Remotive categorizes postings (software,
  devops, design, …); the connector can filter to one category per
  instance — add two instances for two categories.
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
