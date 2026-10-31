# Market statistics

The **Market stats** page (`/postings/stats`) shows where the job market is
moving — how many postings arrive over time, which skills employers ask
for, how demand splits by seniority, company or career family, and what
disclosed pay bands look like. Everything is computed live from the
postings you have connected; nothing is cached or pre-aggregated.

> The page is in beta — the numbers work end to end, but expect rough
> edges and send feedback.

## Choosing a time window

The header switches the whole page between window presets:

| Preset | Meaning |
|---|---|
| `24h`, `7d`, `30d`, `90d` | The stated period ending now. |
| **All time** | Everything that ever arrived. |
| **Custom range** | An explicit `from` → `to` pair (both days inclusive). |

Beside the presets, two global toggles shape every card:

- **Status basis** — `Open` counts only postings that are live right now
  (the same set the postings feed shows), `All` counts every status
  including expired ones. Market history is usually best read on `All`;
  the same toggle decides every card on the page.
- **Compare with previous** — overlays the equal-length period before the
  selected window as ghost bars, so growth is visible without a
  calculator.

## What the page shows

- **"What changed" insights** — deterministic cards that flag notable
  moves in the selected window (volume far above/below the recent norm, a
  work mode or seniority gaining share, a new leading skill). No AI is
  involved — the same numbers you see in the cards raise the flags.
- **Pulse tiles** — new postings in the last 24 hours, 7 days and 30 days,
  each with the change versus the previous period and a 14-day sparkline.
  A tile click opens `/postings` with the matching `posted_within` filter.
- **Postings over time** — a bar chart of the window, split by nothing,
  status, source, work mode, seniority or employment, with the ingestion
  basis visible in the bucket label.
- **Market overview** — count in range versus the previous window, the
  status mix, and a data-coverage summary.
- **Skills in demand** — the most-demanded skills with counts and shares,
  rising and cooling lists against the previous window, a volume ×
  momentum quadrant (rising stars top right), the category mix donut, the
  demand-level histogram and the priority mix. Rows link to
  `/postings?skills=&lt;key&gt;`.
- **Market structure** — one dimension explorer over seniority, work
  mode, employment, contract, education, source, location, company and
  **career family** (demand by the [job catalog](/catalog)'s family tree,
  with an unmapped bucket). Dimensions with a matching list filter link
  through to `/postings`.
- **Salary bands** — per currency on the annualized normalized basis: p25
  – p75 band, distribution buckets (each links to `/postings` with the
  salary floor), medians by seniority. Currencies with too few disclosed
  postings hide the band deliberately.
- **Who is hiring** — companies hiring, companies appearing in the window
  (links to `/companies?status=new`), top hiring companies (link to the
  company pages), the industry mix and openings-per-company buckets.
- **Coverage and freshness footer** — the honest chips: how much of the
  window population discloses salary and location, how much is linked to
  the catalog company, and when each connected source last delivered —
  stalled sources are named.

Numbers, percentages and dates render in your locale format.

## Related pages

- [Postings and search](postings-and-search.md) — the live feed the drill
  links open.
- [Companies](companies.md) — the company directory behind the hiring
  cards.
