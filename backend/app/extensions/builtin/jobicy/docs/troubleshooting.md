# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Sync stops before the cap | The three-page-per-sync limit or the board's `hasMore` ended the walk | Expected; the next sync resumes from the cursor |
| Zero rows for a tag | The tag has no current postings | Clear the tag or try the board's spelling of the discipline |
| `rate-limited` errors | The per-host cap engaged | Lower sync frequency; pagination resumes cleanly afterward |
| Same rows arrive twice across syncs | Cursor state was reset (source re-saved) or the board rotated its cursor | Dedup by external id catches it in-app; reset only when needed |
| `protocol` error in the log | The API's response shape changed | Connector-side fix — report it with the logged detail |
| Rows lack seniority/salary | Jobicy does not publish them for those rows | Not a bug — the fields ride `raw` only when present |
