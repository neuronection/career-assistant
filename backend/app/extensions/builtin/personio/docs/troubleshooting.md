# Personio troubleshooting

**The sync returns zero items.** Check the tenant spelling — an unknown
tenant answers `404`. Personio also empties the feed when the employer has
no open positions.

**Everything is filtered as old.** The watermark is the oldest returned
posting date; after a long pause the first sync may legitimately return
nothing new. Clear the source's sync state (or add a second source) to
re-import the whole feed.

**Rate limited.** Personio throttles aggressive clients. The runtime retries
with backoff and records a `rate-limited` error with the retry hint; leave
the source enabled and the next scheduled sync picks it up.
