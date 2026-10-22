# Using the Personio connector

1. Open **Settings → Tools → Connectors** and add a source with the
   **Personio careers feed** connector.
2. Enter the tenant: for `acme.jobs.personio.de` the tenant is `acme`.
3. Optionally set the feed language (default `en`) and a per-sync item cap.

Each sync fetches the tenant's feed through the polite runtime (SSRF guard,
robots.txt, per-host rate cap, conditional GET) and stores the newest
posting date as the watermark. Items at or below the watermark are skipped
on the next run; changed content still deduplicates by content hash. The
job URL is built as `<tenant>.jobs.personio.de/job/<id>`.
