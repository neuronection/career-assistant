# Assessment and metrics

Career Assistant measures the things that matter for a career decision in one
shared metric language, then uses those measurements in matching, filters and
weight sliders. The **JobTypeMatch** assessment is how you fill in the
parts of your profile that are hard to self-report accurately.

## The JobTypeMatch assessment

Open it from **Profile → Assessment** (`/profile/assessment`). It is a
four-phase profiling pipeline:

1. **Profile foundation** — start from what your profile already says.
2. **Standardized scenarios** — answer a fixed set of scenarios.
3. **AI-generated scenarios** — scenarios generated for you specifically.
4. **Personalized selection** — the most relevant scenarios, chosen for your
   situation.

Runs are **resumable** — you can stop and continue later — and you can
re-run with a custom selection.

### Evidence reconciliation

Scenario answers **refine your skill levels**, but large conflicts with your
self-rated levels are **flagged, never silently overwritten**. You stay in
control of your own data.

## The metric model

Underneath sits a dimension registry that stores what assessments, profile
sections and behaviour measure — with provenance. The fit engine, the filters
and the weight sliders all speak this one language.

### Per-user metric profile

- **RIASEC interest affinities** — the interest vectors that blend into
  interest scoring.
- **Work-values fit** — your values against a job's derived signal.
- **Lifestyle constraints** — with a salary-minimum gate.
- **Per-skill transferability** — for example "your SQL transfers to 12 of 20
  families", derived from the catalog join graph.

### Metric batteries

Bank batteries for RIASEC and work values live in the assessment template
library. Engine dimension lists derive from one spec, so the assessment and
the fit engine cannot drift apart.

### Metric model residuals (opt-in)

- **Revealed preferences** — engagement nudges your RIASEC vector by no more
  than 5% per week, and never touches the exploration slot.
- **Application outcome funnel** — per-family outcomes are **observation
  only** and are never scored.

## Career stages

One switch — **student, early career, experienced, switching or returning**
(derived when unset, always correctable) — retunes:

- Suggested fit weights
- Assessment scenarios grounded in your stage
- Career-path ordering (experience-first)
- Student-only modules such as university intake (gated by feature flags)

The engine stays one engine: stage presets are **suggestions, never hidden
scoring branches**.

## Related

- [Onboarding and your profile](onboarding-and-profile.md) — the sections the
  assessment refines
- [Matching and rankings](matching-and-rankings.md) — where the metrics are used
- [Feature catalog](features.md#assessment--metric-model) — the full model
