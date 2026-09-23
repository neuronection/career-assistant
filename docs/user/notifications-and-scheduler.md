# Notifications and scheduler

Two related systems keep Career Assistant working while you are not watching:
the **notification funnel** (how you hear about things) and the **scheduler**
(what runs periodically).

## The scheduler

One periodic engine runs everything scheduled:

- **Scheduled saved searches** run on your rhythm and ping you on new matches.
- A **weekly digest** rolls up postings and near-misses.
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

- **Channels** (in-app and desktop native toasts; the family's notification
  center is the long-term substrate).
- **Alert rules** — threshold alerts (fit ≥ your line, or new jobs in families
  you follow) with **per-day caps** and **cooldowns**.
- **Quiet hours**, per rule.
- **Click-through deep-links** that open the relevant item.
- **Dedup keys** so the same thing is never sent twice.

Configure preferences in **Settings → Notifications**.

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
