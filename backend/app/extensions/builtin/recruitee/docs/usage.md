# Using the Recruitee connector

1. Open **Settings → Tools → Connectors** and add a source with the
   **Recruitee careers feed** connector.
2. Enter the company subdomain: for `acme.recruitee.com` the company is
   `acme`.
3. Optionally set a per-sync item cap.

Titles and descriptions are read from the offer's English translation when
present, otherwise from the first available locale. Salary ranges keep their
currency and period. The posting URL is the offer's public `careers_url`.
