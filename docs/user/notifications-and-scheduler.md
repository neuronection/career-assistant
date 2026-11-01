# Notifications and scheduler

Two related systems keep Career Assistant working while you are not watching:
the **notification funnel** (how you hear about things) and the **scheduler**
(what runs periodically).

## The scheduler

One periodic engine runs everything scheduled:

- **Scheduled saved searches** run on your rhythm and ping you on new matches.
- A **weekly digest** rolls up postings and near-misses.
- A **daily smart digest** (opt-in) notifies you when the smart ranking
  finds fresh, unseen postings — see [postings and
  search](postings-and-search.md) for the ranking it uses. Enable it in
  **Settings → Notifications** with the **Daily smart matches**
  (`smart_digest`) toggle; the notification deep-links into the living
  smart view (`/postings?sort=smart`) and only fires on days with at
  least one new match. The same daily job prunes the natural-language
  search cache (7 days).
- **Source syncs** refresh your connected boards.
- **Check-ins** and **re-fit sweeps** keep your plan and scores current.
- Follow-up nudges for applications you have not heard back on.

The scheduler **decides *when*** and only **enqueues jobs** — the actual work
runs through the background queue. It supports:

- **Jitter** so runs do not all fire at once.
- **Misfire policies** for when the desktop sleeps (catch up, skip, or move to
  the next slot).
- **Exponential backoff** that tells you when something is stuck.

Configure schedules in **Settings → Scheduler**.

## The notification funnel

All notifications emit through a single funnel, so there is one place that
decides how you are told. It supports:

- **Channels** — the in-app inbox is always on; desktop toasts and browser
  push are mode capabilities; **email** and **webhooks** are opt-in per
  channel and per notification kind.
- **Email** — a notification address (your account email unless overridden,
  confirmed by a one-time link), plus a **digest mode** that batches routine
  email into the weekly digest. The instance SMTP transport is configured by
  an admin under **Settings → Notifications** (the password is sealed at rest
  and never returned by the API). Desktop and self-host use the same channel:
  SMTP is whatever you configure, not an assumed OS mail client.
- **Webhooks** — POST each kind to Slack, Microsoft Teams, Telegram, ntfy or
  a generic JSON endpoint. Presets only shape the payload; the URL is
  user-supplied and passes the same SSRF guard as the web's polite fetch
  runtime (no internal addresses, no redirects, bounded responses). An
  optional shared secret rides a token header. Retries run in the background
  queue with backoff — never inside the request that emitted the event.
  **Send test** writes a real delivery row and marks the channel verified.
- **Calendar and RSS subscriptions** — see below.
- **Alert rules** — threshold alerts (fit ≥ your line, or new jobs in families
  you follow) with **per-day caps** and **cooldowns**.
- **Quiet hours** — toasts are silenced; email waits for the next digest run;
  webhooks still queue in the background; calendar and RSS feeds are pull-only,
  so there is nothing to suppress.
- **Click-through deep-links** that open the relevant item.
- **Dedup keys** so the same thing is never sent twice.

Configure preferences in **Settings → Notifications**. Route individual kinds
to email or a webhook there, and use the follow-up block for the per-stage
routing overrides (`default`, follow-up due, interview check-in, offer
check-in).

## Calendar and feed subscriptions

Two pull surfaces need no channel work and work in any calendar or feed
reader:

- **Calendar (`.ics`)** — one entry per admission deadline, application
  deadline, scheduled interview and follow-up review day. Entry UIDs are
  stable per item, so editing a date updates the existing calendar event.
  Use the **webcal** link in Settings → Notifications to subscribe.
- **RSS/Atom** — new postings for a saved search (or all new postings),
  newest first with a `created_at` cursor for readers that page.

Both use **rotatable tokens**: the token is shown once when minted, stored
only as a hash, can be rotated (the old link stops working immediately) and
revoked. A revoked or unknown token answers `404`.

## Application follow-ups

A daily sweep nudges applied postings with no response (**+7d, +14d** —
adjustable) and switches to congrats/check-in prompts at the interview and
offer stages. Per-application follow-up state is shown inline, and everything
is delivered through the funnel — never double-sent. Preferences live under
`preferences["followups"]` (surfaced at `/me/followups`).

## On the desktop

Closing the window keeps the scheduler running in the tray: sync-now and
saved-search controls, native toasts, quiet hours honored, and misfired runs
caught up on boot. See [Desktop app](desktop-app.md).

## Related

- [Career Autopilot](career-autopilot.md) — goal searches on cadence
- [Settings reference](settings.md) — the scheduler and notification pages
- [Feature catalog](features.md#background--scheduler) — the full engine
