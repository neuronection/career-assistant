# Using the Teamtailor connector

1. Open **Settings → Tools → Connectors** and add a source with the
   **Teamtailor careers feed** connector.
2. Enter the company subdomain: for `acme.teamtailor.com` the company is
   `acme`.
3. Optionally set a per-sync item cap.

Location, remote status, employment type and salary are read from the
embedded schema.org posting. The description prefers the structured posting
description and falls back to the feed's `content_html`.
