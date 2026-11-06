# StepStone / Xing troubleshooting

**`needs-secret`.** The alert URL slot is empty — re-enter the RSS URL; it
is stored sealed and never echoed back.

**The alert returns nothing.** Alerts only contain postings that match the
saved search at fetch time. Widen the search on the board, or check that
the alert is still active.

**Robots or 403 errors.** The board may require the session that created
the alert. Create a fresh alert URL while signed in and replace the slot.
