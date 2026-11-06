# Usage

## Add the source

1. Copy the posting's URL from your browser.
2. Settings → Tools → Connectors → **Add source** → Paste a posting
   URL → paste the URL.
3. Save and sync. The first sync fetches the page and lands the
   posting.

## What a sync fetches

- The page at the URL is fetched once through the polite transport;
  the extracted `JobPosting` fields (title, organization, location,
  salary, employment type, skills, posted/expires dates) land as a
  normal posting.
- Without a `JobPosting` block, the page's `<title>` becomes the title
  and the URL is kept — the record says what the page said, nothing
  more.
- The sync is **not incremental**: this source holds one posting, not
  a feed. Re-syncing re-fetches the same URL; if the posting is taken
  down, the sync logs a `provider` error with the status code instead
  of quietly keeping a phantom listing.

## What to be careful at

- **One posting per source** — the URL is the source; there is nothing
  to walk or page.
- **Pages change** — a re-sync re-reads the live page; a posting that
  was edited or taken down upstream changes or errors accordingly.
- **URL length** — the config field caps at 1000 characters; tracking
  URLs usually fit, sessions-in-the-URL do not and should be cleaned.
