# Usage

## Add the source

1. Settings → Tools → Connectors → **Add source** → Remotive remote
   jobs.
2. Optional config: **Category** (one Remotive category slug, e.g.
   `software-dev`; empty = all) and **Max items per sync** (1–200,
   default 50).
3. Save and sync. Unchanged boards answer with a cached 304 on later
   syncs.

## Sync behavior

- Rows land with title, company, URL, category, location note and
  publication date; the job URL is the original `remotive.com` link.
- The watermark cursor deduplicates rows already seen (older rows are
  not re-fetched); state rides the instance's `next_state`, never
  user config.
- Rows sort newest-first within a sync before the cap applies — the
  cap eats the OLDEST rows, not the newest.

## What to be careful at

- **Attribution** — keep the remotive.com URLs intact when exporting
  or sharing rows.
- **Category is per-instance** — filtering two categories means two
  sources (each with its own watermark).
