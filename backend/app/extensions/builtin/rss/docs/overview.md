# RSS / Atom feed

Job postings from any RSS 2.0 or Atom feed — the format half the
web's job boards, newsletters and "new openings" pages already speak.

- **Two formats, one connector.** RSS 2.0 `<item>` entries and Atom
  `<entry>` elements both land; mixed or either-only feeds work.
- **Identity is the feed's.** The RSS `<guid>` (or link) and the Atom
  `<id>` become the posting's external id — deduplication follows the
  feed's own identity, not a guess from the title.
- **Watermarked incremental syncs.** Unchanged feeds cost one cheap
  304: the polite transport sends the feed's ETag/Last-Modified back
  as conditional-GET validators.

## When to use it

The employer, board or community publishes a feed of openings —
typical for niche boards, university career pages and company news
feeds that include jobs.

## When NOT to use it

Pages that only look like feeds (a listing without XML — use the
paste-a-URL connector), or a public ATS board where the structured
ATS connector gives richer, more stable records.
