# Troubleshooting

## `provider` — "workable fetch failed with status 404"

The account slug does not exist (typo, or the company moved off
Workable). Open the company's careers page: the slug is the path segment
of its `apply.workable.com/<account>` URL.

## Empty feed, status ok

- The account exists but publishes no jobs right now (expected — the
  next sync picks them up).
- `max_items` is set below the number of openings — raise it.

## Jobs missing fields (no city, no employment type)

The widget payload omits what the company left blank in Workable — the
connector passes through what exists; nothing is invented.
