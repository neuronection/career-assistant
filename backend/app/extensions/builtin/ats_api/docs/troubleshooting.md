# Troubleshooting

Symptom → cause → fix for the ATS public API connector.

| Symptom | Cause | Fix |
|---|---|---|
| Sync succeeds but 0 postings, first run | Wrong org slug — the board API answered (usually an empty job list or a 404 surfaced as a provider error in the sync log) | Re-read the slug from the employer's board URL (see Usage); a Greenhouse slug does not transfer to Lever |
| Sync log shows a `provider` error with status 401/403 | The board sits on a partner tier that wants the token, or the pasted token is wrong/expired | Paste a fresh token in the source's secret field; public boards never need one |
| Sync log shows `net-denied` | A redirect or rewrite left the three declared API hosts (`boards-api.greenhouse.io`, `api.lever.co`, `api.ashbyhq.com`) — refused by the domain scope, by design | Nothing to configure: if the employer's board really lives elsewhere, that board is out of this connector's scope |
| Sync log shows `rate-limited` | Many ATS sources synced on one schedule hit the per-host cap | Stagger the sources' schedules; the cap is per host and shared politely |
| Postings stop updating but the board changed | The board's cache validators (ETag/Last-Modified) went stale after a provider-side incident | Run the sync again; a forced re-sync re-walks the board when the validators change |
| Duplicate postings after re-adding a source | The same board registered twice under two sources | Keep one source per board; external ids deduplicate within a source, not across sources |

Nothing here helps? The sync log's error code is the contract's closed
vocabulary — `extension-troubleshooting` in the user guide explains what
each code means and what it rules out.
