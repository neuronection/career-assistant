# Calendar & RSS feeds

Get your career dates — deadlines, interviews, review days — into whatever
calendar or feed reader you already use. No account linking, no OAuth: you
subscribe to a private link.

## What the calendar feed contains

| Moment | Appears as |
|---|---|
| Admission deadlines | all-day event on the date |
| Application deadlines | all-day event on the date |
| Scheduled interviews | timed event (default 60 min) |
| Follow-up review days | all-day event |

Each entry has a **stable id**, so when a date changes your calendar *updates*
the event in place instead of adding a duplicate.

## How to subscribe

1. Go to **Settings → Notifications → Calendar and RSS**.
2. Press **New calendar token**. You can scope it to a saved search (only
   matching postings) or to all new postings.
3. **Copy the link immediately** — the token is shown once and never again.
   (Or press **Subscribe in your calendar (webcal)** to hand it straight to
   your calendar app.)
4. Add it to your calendar:
   - **Google Calendar** → *Other calendars* → **From URL** → paste
   - **Outlook / Microsoft 365** → *Add calendar* → **Subscribe from web** → paste
   - **Apple Calendar** → *File* → **New Calendar Subscription** (you can pick
     the auto-refresh interval here)
   - **Thunderbird** → *New Calendar* → **On the Network** → iCalendar

An RSS feed works the same way for feed readers (**New RSS token**).

## Does it update automatically?

Yes — with one caveat: there is no push notification, so your calendar polls
the link on its own schedule.

| | |
|---|---|
| **Career Assistant** | always current — the feed is rebuilt from live data on every request and is never cached |
| **Google Calendar** | refreshes roughly every **8–24 hours** (Google does not let you force it) |
| **Outlook / Microsoft 365** | roughly every **3–24 hours** |
| **Apple Calendar** | your choice — 5 minutes to 1 month |
| **Thunderbird** | your choice, per subscription |

So a rescheduled interview is correct here immediately and lands in Google
within about a day. Nothing is lost in between — the event simply updates when
the calendar next checks.

## Tokens and safety

- The token is a **bearer credential in the link** — anyone holding the link
  can read the feed. Treat it like a password.
- It is shown **once** at creation; only a hash is stored, never the token.
- **Rotate** issues a new link and invalidates the old one — do this if you
  think the link leaked.
- **Revoke** kills the subscription entirely. A revoked or unknown token
  returns "not found", never a fallback.
- The feed carries only the dates and titles above — no notes, no application
  details beyond what's listed.
