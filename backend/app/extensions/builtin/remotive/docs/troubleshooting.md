# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Zero rows for a category | The value doesn't match any posting category (titles like "Software Development", matched case-insensitively) | Check the category shown on the posting; leave empty for all rows |
| `rate-limited` errors | The per-host cap engaged (429 or local cap) | Lower sync frequency; the runtime retries after the advertised delay |
| Older postings never arrive | The watermark skips rows seen in earlier syncs (incremental by design, not a replay) | Re-save the source to reset state and pull a fresh first page |
| Category filter seems ignored | The filter applies client-side over the feed's categories | Match the category text a posting carries; check the sync log's landed rows |
| `protocol` error in the log | The feed's response shape changed | Connector-side fix — report it with the logged detail |
| `net-denied: robots.txt` | Remotive's robots.txt disallows the fetched path (their `/api/*` is off-limits — this connector rides the allowed `/remote-jobs/feed`) | Never repoint the source at the JSON API; if the feed itself becomes disallowed the connector needs a new polite endpoint |
