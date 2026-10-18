# Usage

## Add the source

1. Settings → Tools → Connectors → **Add source** → Arbeitnow job
   board.
2. Optional config: **Tag filter** (only rows carrying at least one
   tag; empty = everything) and **Max items per sync** (1–300,
   default 100).
3. Save. The first sync fetches the board; subsequent syncs ride
   conditional GET — an unchanged board costs one cheap 304.

## Sync behavior

- Rows land as postings with title, company, URL, location, tags and
  publication date; the job URL is the original `arbeitnow.com` link.
- Duplicate rows across syncs deduplicate by external id; deleting a
  posting locally re-imports it on the next sync while it stays on the
  board (a source is a feed, not a mirror of your decisions).
- The watermark cursor plus ETag state rides the instance's
  `next_state` — never user-visible config.

## What to be careful at

- **Attribution** — the API's meta terms ask for reasonable use and a
  link back; keep rows' URLs intact when exporting or sharing.
- **Rate caps** — the polite runtime caps requests per host; if you
  sync many sources on one schedule, stagger them.
