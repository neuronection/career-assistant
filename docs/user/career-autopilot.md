# Career Autopilot

Career Autopilot is a goal-driven agent for finding live openings. Describe
a goal once — for example "junior QA role, remote, €30k+" — and it searches
your connected boards on a cadence or on demand, ranks results by your
deterministic fit score, and delivers a curated shortlist.

Open it at `/autopilot`.

## What a run does

1. **Plans** multiple query and filter variants from your goal.
2. **Filters noise** — postings you have seen or applied to, terms you never
   want, and a per-goal cooldown.
3. **Ranks** by your deterministic fit score (see
   [Matching and rankings](matching-and-rankings.md)).
4. **Explains** the shortlist: every explanation cites verbatim quotes
   verified against the posting's own text.

A **"what I searched & why"** timeline shows each run's work, so the agent's
reasoning is inspectable rather than opaque.

## Cadence and budgets

- **On cadence or on demand** — schedule a goal and it runs periodically
  through the scheduler, or trigger a run yourself.
- **Budgets hard-cap runs.** When a run hits its budget, partial results
  still ship rather than being thrown away.

## Steering the agent

- **"More like this" / "Hide like this"** teaches the goal's constraints.
- **Dismissing a whole shortlist pauses the goal** — it stops spending on
  something you do not want.
- **Three empty runs trigger a refine-the-goal nudge** — never wasted spend.

Autopilot **never auto-applies** anything: it proposes, you decide.

## Related

- [Postings and search](postings-and-search.md) — connect the boards it searches
- [Notifications and scheduler](notifications-and-scheduler.md) — how cadence works
- [Feature catalog](features.md#career-autopilot) — the full agent behavior
