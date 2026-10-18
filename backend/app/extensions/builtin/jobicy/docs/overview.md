# Jobicy remote jobs

A bundled connector that syncs job postings from Jobicy's public
remote-jobs API v2 — free, no credentials (no secret slots by design).

- **Remote board with geography.** Every row is remote; the geo
  restriction rides each row's country field and geo note.
- **Tag filter + cursor pagination.** Filter by tag; the connector
  walks Jobicy's cursor pages (`nextCursor`/`hasMore`) up to three
  pages per sync under the runtime's per-host rate cap.
- **Credit where due.** Jobicy's friendly notice asks for credit and
  application links — the posting URL IS the `jobicy.com` URL, so
  applying happens on the source site.

## When to use it

Remote-only searches with a tag focus (e.g. a discipline you track),
refreshed on your sync schedule, zero setup.

## When NOT to use it

On-site/hybrid searches (use Arbeitnow for German/European boards) or
broad unfiltered pulls beyond a few hundred rows per sync — cap and
paginate instead of hammering the board.
