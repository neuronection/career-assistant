# Job radar

The job radar is your saved job-search configuration — tell the app
once what you are looking for, and use it everywhere. It lives under
**Settings → Job radar** (`/settings/radar`).

> The radar stores exactly what you enter — nothing is inferred. A
> salary floor is compared on the **annualized basis** (see
> [Postings and search](postings-and-search.md)), so a monthly and a
> yearly posting compete equally; an unknown salary never matches a
> floor. An empty radar filters nothing — configure at least one thing
> and use **Preview matches** to see what it catches before saving.

## What to configure

- **Keywords** — role or topic words; a posting matches when any
  keyword appears in its title or employer.
- **Locations** — preferred city/country rows, or a plain "remote" row.
- **Work mode** — on-site / hybrid / remote preference.
- **Salary floor** — an annual figure with its currency.
- **Seniority** — the bands you are aiming at.
- **Match digest** — off, instant, daily or weekly (digest delivery
  arrives with the notifications wave).

Save it once; **Preview matches** shows what the radar would match
right now without saving.

## Where it is used

- **Explore** (`/postings/search`) — the **My radar** button runs your
  saved configuration as a live search; "Clear radar" returns to the
  open filters.
- **Ingestion** — a job source set to **Follow my radar** takes its
  keywords and location from the radar instead of its own static
  settings. The radar's keywords are grouped into roles (by the AI
  curator when a provider is configured — the normal case; a
  deterministic auto-merge groups near-duplicates otherwise, and
  upgrades automatically once AI is available), and each sync searches
  one focused group, rotating round-robin (one search per sync — traffic
  stays constant however many keywords the radar holds). The source's
  edit form shows the effective query and rotation position. Radar
  changes are picked up automatically on the next sync.
- **Match digests** — the radar is evaluated live each time its digest
  runs (instant ≈ every 15 minutes, daily at 08:00 UTC, weekly on
  Mondays), so the matches always reflect the current postings. At most
  one digest per bucket is sent, and only when **unseen** matches
  remain — an unchanged set never re-notifies within the bucket.

The radar is per profile: switch profiles and each one keeps its own
radar. Sources without *Follow my radar* follow their own admin
configuration ([Add a job source](add-a-job-source.md)).

## Related

- [Postings and search](postings-and-search.md) — the feed and filters
  the radar drives.
- [Notifications and scheduler](notifications-and-scheduler.md) — where
  match digests appear.
