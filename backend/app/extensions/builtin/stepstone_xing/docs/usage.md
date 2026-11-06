# Using the StepStone / Xing connector

1. Create a job alert on StepStone or Xing and copy its RSS URL.
2. Open **Settings → Tools → Connectors**, add a source with the
   **StepStone / Xing job alerts** connector, choose the board and paste the
   URL into the secret field.
3. Save; the sealed slot is shown as set with a short hint, never as the
   value.

Each sync fetches the feed through the polite runtime (SSRF guard,
robots.txt, per-host rate cap, conditional GET). RSS items carry a
`pubDate`; the oldest returned date becomes the watermark and older items
are skipped on the next run.
