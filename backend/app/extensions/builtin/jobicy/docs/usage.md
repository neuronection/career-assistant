# Usage

## Add the source

1. Settings → Tools → Connectors → **Add source** → Jobicy remote
   jobs.
2. Optional config: **Tag** (one tag, e.g. `designer`; empty = all)
   and **Max items per sync** (1–200, default 50; the connector walks
   up to three cursor pages per sync to reach it).
3. Save and sync.

## Sync behavior

- Rows land with title, company, URL, location (country + geo note),
  seniority where published, and application/description links; the
  job URL is the original `jobicy.com` link.
- Pagination rides Jobicy's `nextCursor`/`hasMore`: a sync stops at
  your cap, at the page limit, or at the board's end — whichever
  comes first; the next sync resumes from the saved cursor state.
- ETag/Last-Modified state rides the instance's `next_state` — an
  unchanged first page answers with a cached 304.

## What to be careful at

- **Apply on the source** — follow the jobicy.com URL; the app never
  applies for you.
- **Page cap per sync** — a very large cap still stops at three pages;
  raise sync frequency rather than the cap if you need deep history.
