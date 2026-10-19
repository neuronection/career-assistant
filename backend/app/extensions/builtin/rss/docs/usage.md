# Usage

## Add the source

1. Copy the feed URL — the one your reader subscribes to, ending in
   `.xml`, `/rss`, `/feed` or `/atom` more often than not.
2. Settings → Tools → Connectors → **Add source** → RSS / Atom feed →
   paste the URL.
3. Save and sync.

## The watermark, in plain terms

- The **first sync** walks the whole feed and lands what it finds.
- Every later sync sends the stored validators (ETag /
  Last-Modified) with the request. An unchanged feed answers
  **304 Not Modified** and the sync finishes having fetched nothing —
  by design, that is the cheap path.
- A changed feed answers 200 with the full document; entries are
  deduplicated by their guid/id, so only genuinely new postings land
  as new rows.
- The watermark lives in the source's sync state, never in your
  editable config — there is nothing to reset by hand; re-syncing
  after a feed outage picks the change up on the next pass.

## What to be careful at

- **Entries need identity** — an RSS item without `guid` falls back to
  its link, then its title; feeds that publish neither re-land as new
  postings on every sync (see Troubleshooting).
- **Descriptions ride along raw** — the feed's HTML description is
  kept for matching and display; it is upstream content, not app copy.
- **Feeds move** — a feed that redirects off its original host keeps
  working only while the polite transport's rules allow the hop; pin
  the final URL when a board announces a move.
