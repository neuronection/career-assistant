# Career Autopilot

Career Autopilot is a goal-driven agent for finding live openings. Describe
a goal once — for example "junior QA role, remote, €30k+" — and it searches
your connected boards on a cadence or on demand, ranks results by your
deterministic fit score, and delivers a curated shortlist.

Open it at `/autopilot`.

## What a run does

1. **Plans** several query and filter variants from your goal — grounded in
   your profile: your skills (and the taxonomy skills around them), your
   education level, your location, and the seniority you asked for. Each
   variant searches by **keyword**, so multi-word concepts match titles and
   employers instead of being treated as one exact phrase.
2. **Searches two ways** — by keyword variants and **by meaning** over the
   posting embeddings already stored. The semantic pass is a recall source,
   not a shortcut: every posting it proposes still passes the same
   deterministic gates before it can reach the shortlist.
3. **Filters noise** — postings you have seen or applied to, terms you never
   want, and a per-goal cooldown.
4. **Ranks** by your must-terms first and your deterministic fit score
   second — constraints are promises, fit is preference (see
   [Matching and rankings](matching-and-rankings.md)). Every finding states
   how many of your must-terms it covers.
5. **Explains** the shortlist: every explanation cites verbatim quotes
   verified against the posting's own text.

A **"what I searched & why"** timeline shows each run's work, so the agent's
reasoning is inspectable rather than opaque. Each search reports how many
postings it found in total and how many it actually examined, and the windows
it scans hold **fresh** postings only — ones you have not seen, applied to or
hidden — so a long browsing history never crowds new vacancies out of a run.

Semantic coverage grows as your postings get embedded: an admin recompute
(Settings → AI Configuration) embeds them today, so a fresh board's postings
join the by-meaning pass only once they have an embedding. Keyword search
works immediately — an embedding failure never breaks a run.

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
