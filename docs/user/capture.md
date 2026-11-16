# Capture a posting

Career Assistant can take one job posting from anywhere on the web without
a connector. The capture path is the same **paste-a-URL** path it has always
had: one page, fetched once through the guarded transport, then an ordinary
posting you can rank, tailor and apply to.

## From the posting page

Add this app to an existing posting's URL:

```
/postings?capture=<the posting URL>
```

The **Capture a posting** dialog opens with the URL prefilled. Nothing is
fetched until you confirm. If the role is already in the app, capture
returns that posting instead of creating a duplicate — the canonical URL
(tracking parameters stripped) is the idempotency key.

## The bookmarklet

Open `/postings/capture-help` and drag the **Capture to Career Assistant**
button to your bookmarks bar. On any job board, click it: it opens this app
with `?capture=<that page>`, and you confirm in the dialog. The bookmarklet
carries no secret and never captures on its own.

## What can go wrong

- A page that is private, reserved or not HTTP(S) is refused before any
  fetch (the same SSRF guard as every other outbound fetch).
- A page with no structured `JobPosting` data still lands, with the page
  `<title>` as the honest title.
- Captured postings are ordinary postings: they show their source as
  **Captured postings**. A second capture is idempotent — it returns the
  existing row instead of fetching or overwriting it.
