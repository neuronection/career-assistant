# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Zero rows for a category | The slug is wrong or empty for the current board | Check Remotive's category list; leave empty for all rows |
| `rate-limited` errors | The per-host cap engaged (429 or local cap) | Lower sync frequency; the runtime retries after the advertised delay |
| Older postings never arrive | The watermark skips rows seen in earlier syncs (incremental by design, not a replay) | Re-save the source to reset state and pull a fresh first page |
| Category filter seems ignored | The filter applies at fetch URL level — an empty slug fetches everything | Set the slug exactly; check the sync log's fetched URL |
| `protocol` error in the log | The API's response shape changed | Connector-side fix — report it with the logged detail |
