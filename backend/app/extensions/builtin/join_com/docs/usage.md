# Using the JOIN.com connector

1. Open **Settings → Tools → Connectors** and add a source with the
   **JOIN.com careers feed** connector.
2. Enter the numeric company id and the company slug from the careers URL.
3. Leave the page size at 5 — the public API rejects larger pages.

Salary amounts arrive in minor units (cents) and are converted to the
display currency, so `9000000 EUR` becomes `90 000 EUR`. The feed returns
at most five items per page; a sync walks up to three pages under the
runtime's per-host rate cap and stops at the item cap. The newest posting
date becomes the watermark.
