# Arbeitnow job board

A bundled connector that syncs job postings from Arbeitnow's public
job-board API — live German/European listings, free, no credentials
(no secret slots by design).

- **Public API, polite runtime.** Requests ride the app's polite
  transport: robots honored, conditional GET (ETag/Last-Modified)
  cached, a per-host rate cap, and the declared domain scope
  (`www.arbeitnow.com`) enforced on every hop.
- **Tag filter + item cap.** Keep only rows carrying at least one of
  your tags; cap rows per sync (1–300, default 100).
- **Attribution.** Arbeitnow's meta terms ask for reasonable use and a
  link back — every synced row keeps the original `arbeitnow.com` job
  URL, and the source list shows the attribution row.

## When to use it

You are looking for German/European positions (including remote ones
tagged as such) and want a zero-configuration source that refreshes on
your sync schedule.

## When NOT to use it

Non-European markets (use Remotive/Jobicy for remote-first boards, or
an ATS/URL source for a specific employer), or salary-heavy research —
Arbeitnow rows rarely carry salary bands.
