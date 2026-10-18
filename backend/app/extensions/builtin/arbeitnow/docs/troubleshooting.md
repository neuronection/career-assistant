# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Sync returns zero rows | Tag filter excludes everything, or the board's response changed shape (typed `protocol` error in the sync log) | Clear the tag filter; check the source's error detail — shape changes are fixed connector-side |
| `rate-limited` errors | The per-host cap engaged (429 from the API or the local cap) | Wait or lower sync frequency; the runtime retries after the advertised delay |
| Same rows re-imported after deletion | Expected: a source is a feed — a row still on the board returns on the next sync | Hide/reject rows in the app, or narrow the tag filter |
| Results look stale | Conditional GET serving cached 304s while the instance state is ahead | Force a full refresh by re-saving the source (drops cache state) |
| `net-denied` in the log | A redirect left the declared domain scope (`www.arbeitnow.com`) | Rare (API is single-domain); report it — the runtime refuses out-of-scope hops by design |
