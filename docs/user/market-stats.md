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
- **When the market posts** — the whole window as a weekday × hour grid
  in UTC (the deterministic clock heat map), busiest cell named below it.
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

## When the market posts

The **When the market posts** card sits right after the volume chart and
shows the whole window as a weekday × hour grid — 168 cells, Monday
through Sunday across the top rows and hours 00–23 along the columns.
Each posting falls into the cell of its effective posted time, so the
grid answers "when does hiring actually land?" at one glance.

- All times are **UTC** — the grid states so on every cell and in its
  caption; you always know which clock a busy day belongs to.
- Cells shade from muted (empty) through the shared heat ramp, and the
  single busiest cell is ringed; the caption below names it, e.g.
  "Busiest: Wed 09:00 UTC".
- The grid shares the page's window and status basis — switch the header
  toggles and the clock re-reads the same population as every other card.

## Chart or data table

Every data card carries a small Chart ⇄ Data toggle (default: chart).
The **Data** view is the card's own table — the same rows the CSV export
downloads, one shared source: if the export says 42, the table says 42.
The posting clock's table is its condensed twin (totals per weekday and
per hour plus the peak), not all 168 cells. The charts stay available to
screen readers through descriptions on the textual lists.

## Compare any window

The header's compare control has three states:

- **Previous** (default) — the overlaid comparison series shows the
  equal-length window that came right before the selection.
- **Custom** — pick any two dates and the comparison line shows that
  range instead, aligned by bucket position ("aligned by offset" — the
  x-axis stays your selected window). The page tells you when the two
  grids were not the same length. A comparison range that produces too
  many buckets for the chart declines politely with a hint instead of
  breaking the page.
- **Off** — the volume chart alone.

While a split (status, source, …) is active, the overlay pauses — split
series and comparisons are two questions about the same data, answered
one at a time. The comparison lives in the page URL, so a bookmarked
view keeps it.

## Copy the view

The header's Copy link button puts the page's full URL state (window,
custom range, status basis, comparison) on the clipboard — paste it to
share exactly what you were looking at. It works inside the desktop app
where the raw clipboard API is unavailable.

## Related pages

- [Postings and search](postings-and-search.md) — the live feed the drill
  links open.
- [Companies](companies.md) — the company directory behind the hiring
  cards.
