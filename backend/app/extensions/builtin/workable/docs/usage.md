# Usage

1. Find the account slug: it is the path segment of the tenant's careers
   URL (`apply.workable.com/skroutz` → account `skroutz`).
2. Add a job source with the connector **Workable careers feed** and set
   **Workable account** to that slug.
3. Save — the first sync fetches every published job; later syncs send
   conditional validators (ETag) and only new postings are ingested.

The connector reads the widget API with no credentials and no account
access: nothing to paste, nothing to rotate. `max_items` caps each sync
(1–300).
