# Matching and rankings

Career Assistant scores jobs two ways at once — with AI, and deterministically
from your structured profile — and lets you add your own verdict. No single
number silently decides anything: every score comes with a rationale you can
read, agree or disagree with, and override.

## AI match insights

For any job, ask for an AI match. You get a score from 0–10 plus structured
rationale:

- **Positives** — what fits.
- **Negatives** — what doesn't.
- **Missing prerequisites** — what you would need first.

The score and rationale are generated through the audited AI pipeline and
stored with the job, so you can revisit them.

## Your voice counts

Alongside the AI score you can:

- **Score the job yourself** (0–10).
- **Set an interest status** (for example interested, not interested, maybe).

AI and human scores coexist. Rankings can combine both, and your status is
never overwritten by the AI.

## The deterministic fit engine

Independently of any AI call, every job gets a transparent 0–10 fit score
with a **per-dimension breakdown** you can inspect and re-weight:

| Dimension | What it measures |
|---|---|
| Skills | Your skill levels against the job's required skills |
| Education | Your education against the job's requirements |
| Experience | Your experience against what the role expects |
| Location | Your location/remote constraints |
| Interests + work style | Tag overlap blended with RIASEC interest affinity vectors |
| Work values | Your values against the job's derived signal (including benefit kinds) |

Two rules keep the engine honest:

- **No popularity or demand term ever touches the score.** Demand is shown
  as information, never folded into fit.
- **Hard-constraint gates move jobs, they don't delete them.** A job that
  fails a gate (for example a salary minimum or a location constraint) moves
  to a **"Stretch goals"** view with an explanation, rather than disappearing.

Because it is deterministic, you can re-weight the dimensions and watch the
rankings change.

## Rankings and filters

The **Rankings** page (`/rankings`) lists jobs by score, and you can slice by
filters and by your own status. Rankings combine AI score, your score and
interest status.

## Compare tray

Pick 2–4 jobs into the compare tray to see them side by side at
`/compare`: per-dimension fit, gates, education, demand and salary. You can
also ask the chatbot to compare them for you (see
[Chat and proposals](assistant-chat.md)).

## Express start and target mode

Already know the job you want? **Express start** lets you type it, pick your
targets and answer two questions. Live postings, alerts and suggestions start
immediately, and a **target-mode dashboard** shows open jobs, the salary
band, top employers and adjacent careers, plus a completeness ring that
shows exactly which five-minute step sharpens your results next.

## Related

- [Explore the job catalog](explore-the-catalog.md) — where the jobs come from
- [Assessment and metrics](assessment.md) — refine the inputs to the fit engine
- [Postings and search](postings-and-search.md) — live openings inherit your fit
