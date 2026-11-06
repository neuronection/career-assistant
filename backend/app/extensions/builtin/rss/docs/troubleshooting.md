# Troubleshooting

Symptom → cause → fix for the RSS / Atom feed connector.

| Symptom | Cause | Fix |
|---|---|---|
| Sync log shows a `protocol` error mentioning a parse error | The URL serves something that is not XML (an HTML page, a JSON error) — the feed is wrong or the board changed its URLs | Open the URL in a browser; use the real feed URL, or switch to the paste-a-URL connector for plain pages |
| Sync log shows a `provider` error with a status code | The feed answered non-200 — moved, gated, or temporarily down | Re-check the URL; a permanent 301/410 means re-adding the source with the new address |
| Every sync lands the same postings again | The feed's items carry no `guid`/`id` and no stable link — identity falls back to the title, which the feed rewrites | Prefer a different feed for that board; the connector cannot deduplicate what the feed does not identify |
| Sync finishes instantly with 0 postings — is that right? | Yes, usually: the feed answered 304 Not Modified, the watermark's cheap path | Nothing to fix; a genuinely emptied feed looks the same — the sync log distinguishes the 304 from an empty document |
| Postings disappear locally after disappearing from the feed | Correct behavior — a source is a feed, not a mirror of your decisions; removal follows the source's retention | Save the posting (or its match) locally before it leaves the feed |
| Feed works in a reader but not here | The reader may accept feeds this connector's transport must fetch politely (auth-gated, unusual schemes) | Public, keyless feeds only — the same rule every bundled connector follows |

Nothing here helps? The sync log's error code is the contract's closed
vocabulary — `extension-troubleshooting` in the user guide explains what
each code means and what it rules out.
