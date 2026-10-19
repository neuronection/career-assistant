# Paste a posting URL

One posting, fetched from a URL you paste: the connector downloads the
page, reads its schema.org `JobPosting` structured data, and lands it
as a single posting you can match, save and explain like any other.

- **No board, no account.** The source is one URL — the exact posting
  you are looking at in your browser.
- **Structured data first.** The page's JSON-LD `JobPosting` block
  fills title, organization, location, salary, employment type, skills
  and dates when the page carries one.
- **Honest fallback.** No structured data? The page's `<title>` becomes
  the posting title and the URL is kept — a real, if thin, posting
  record, never an invented one.

## When to use it

You found a posting somewhere this app has no connector for — a
careers page without structured data, a posting shared in a chat, a
closing-soon listing you want matched against your profile today.

## When NOT to use it

A whole board or feed (that is what the other connectors are for), or
bulk imports — one source holds one posting; twenty postings means
twenty sources, which is honest but rarely what you want.
