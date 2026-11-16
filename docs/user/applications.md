# Track your applications

The application tracker keeps the whole search in one place: what you
sent, when you last heard from the team, when the next follow-up is due
and how each application ended. It is deliberately **not** an
auto-apply tool — Career Assistant reminds and records; the human
applies.

Open it from the sidebar at `/applications`.

## Track a posting

Open a posting and choose **Track application**. That creates the
application row, marks the posting as applied and opens its drawer.
Clicking **Apply** on a posting card records the same state as before;
the tracker is where it becomes a pipeline.

The **Tailor & apply** button takes the review-first route: the
[application kit](/postings/:ref/kit) opens instead, and **Mark as
applied** there creates the same tracker row with the documents you
choose. See [The application kit](application-kit.md).

Each row is one application: the engagement flags you already know
(seen, saved, hidden) stay on the posting, while stage, dates,
documents, notes and the event timeline live on the application.

## Board and list

The tracker opens as a **board** — one column per stage: Applied,
Screening, Interview, Offer, Accepted and Closed (rejected or
withdrawn) — and toggles to a **list** view. The choice is per visit;
the board is the default.

A card shows the role and organization, the stage, applied and deadline
dates, the next follow-up, thumbnails of the CV and cover letter linked
to the application, and a dot when the application changed since you
last opened it.

## The application drawer

Open any card (or a follow-up notification) to reach the drawer:

- **Timeline** — every event newest first: stage moves, notes, document
  links and follow-up snoozes, with who wrote them (you, the assistant
  or the system).
- **Move stage** — forward or backward, freely. Every real move writes
  exactly one stage-change event; moving to Accepted, Rejected or
  Withdrawn closes the application.
- **Add a note** — appends a note event and keeps the rolling note line
  on the application.
- **Documents sent** — link the CV and cover letter you actually sent.
- **Follow-up** — snooze the next reminder by a number of days.
- **Close application** — choose an outcome (accepted, rejected,
  withdrawn, expired, no response). Accepted, rejected and withdrawn
  also move the stage; expired and no-response close without changing
  it.

The drawer's **Open kit** link (and the **Kit** button on every card and
row) takes you to the application's full kit page at
`/applications/:id` — requirement report, CV variant, cover letter,
answer prompts, checklist and this same timeline in one place. See
[The application kit](application-kit.md).

Closed applications stay in the tracker under Closed and drop out of
the dashboard funnel and follow-up queue.

## Import a calendar

**Import .ics** on the applications page reads a Google or Outlook
calendar export and proposes interview events linked to your existing
applications (by organisation or role in the event text). Nothing is
written until you review and press **Apply import**: timezones are
converted to UTC, all-day events stay all-day, events with no matching
application are listed as proposals only, and a second import of the same
event (same UID, or same application + start + summary) is flagged as a
duplicate instead of creating another timeline row. The outbound calendar
feed is unchanged.

## Follow-ups

Follow-up reminders are proactive nudges, not obligations. The
assistant schedules them from your cadence — by default 7 and 14 days
after applying — and adds a check-in at the Interview and Offer stages
while those are switched on.

Change the cadence in **Settings → Notifications → Application
follow-ups**, or from the tracker's **Follow-up settings** button: the
master switch, the cadence steps in days and the milestone check-ins.
Reminders arrive through your notification channels and deep-link into
the application's drawer. The tracker also shows the next follow-up
date at the top of the page.

## Response-rate coaching

The applications page shows a **tailored vs untailored** response-rate card
over your own applications. *Tailored* means a CV variant or cover letter
was linked before applying; a response is any stage at screening or later
(including a rejection — the employer replied). Each group discloses its
`n` and the card hides both rates until each group has at least 10
applications, then offers one next action. It is descriptive association
only: no cross-user comparison, no causal claim and no score.

## Offer comparison

Record an offer from an application's drawer: currency, amount and period
(year, month or hour), benefits, location, monthly cost of living and the
decision deadline. **Compare offers** (`/applications/offers`) annualizes up
to four offers — year ×1, month ×12, hour ×2080 — and shows the annual cost
of living and the net before/after it.

- Only the details you entered are shown; benefits are never invented and
  missing values are **—**.
- Amounts are **not** converted between currencies. A mixed-currency
  comparison is flagged so you compare within one currency.
- The page is arithmetic, not negotiation advice or a recommendation.

## The dashboard funnel

The dashboard shows the real funnel — **saved → applied →
interviewing → offers** — instead of a bare count. Each number links
into the tracker.

## Asking the assistant

The assistant can read your pipeline, one application's timeline and
your merged application and university-admission deadlines. Stage
changes and notes proposed in chat are **confirmation cards**: nothing
changes until you approve the card, and the approved call runs through
the same service the forms use. Approving records the event as the
assistant's, so the timeline stays honest.
