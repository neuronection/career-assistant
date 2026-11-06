# Market intelligence

The **Market intelligence** page (`/postings/stats`) is the dashboard over
your live job market: how many postings arrive, which skills employers ask
for, how demand splits by seniority, company or career family, and what
disclosed pay looks like. Everything is computed live from the postings you
have connected; nothing is cached or pre-aggregated.

> The page is in beta — every card below works end to end, but expect rough
> edges and send feedback.

## Tabs

The page groups the existing cards into five tabs. Every tab reads the same
window, status basis and filters, so switching tabs compares the same
population.

| Tab | What it answers |
|---|---|
| **Overview** | What changed (deterministic insights), the pulse tiles, the in-range count and the status mix. |
| **Demand** | Postings over time (split and compare), when the market posts (the 24-hour clock), and market structure by one dimension. |
| **Skills** | The most-demanded skills, rising and cooling lists, the volume × momentum quadrant, the category mix, the demand-level histogram and the priority mix. |
| **Pay** | Per-currency salary bands on the annualized normalized basis, distribution buckets and medians by seniority. |
| **Companies** | Companies hiring, new companies, the top hiring list, the industry mix and openings per company. |

## Filters

One filter bar scopes every card:

- **Time** — `24h`, `7d`, `30d`, `90d`, **All time**, or a custom `from` →
  `to` range.
- **Status basis** — `Open` counts only postings live right now (the same
  set the postings feed shows); `All` counts every status except postings
  that were hidden. The same basis shapes every card, so a card's row count
  matches the list its drill opens.
- **Compare** — off, the equal-length previous window, or a custom B range.
  The comparison overlays the volume chart on the same filtered population;
  it pauses while a split is on.
- **Segments** — keywords, source, company, career family, seniority, work
  mode, employment, contract, education, city, country, skills (with a
  match-all/match-any mode) and a salary floor. Admins additionally get an
  "include postings I hid" debug switch; for everyone else hidden rows
  stay out of the aggregates.

On a narrow window (phone, or the desktop app at its 640×480 minimum) the
segments move behind the **Filters** button, which shows how many filters
are active. Every applied filter appears as a removable chip; **Clear all**
resets them in one click. The whole view — tab, window, basis, comparison
and every segment — lives in the URL, so a bookmarked link reopens exactly
what you saw.

## Drills

Clicking a structure row or a skill opens `/postings` with the **whole**
page state: the window as the matching `posted_within` preset, the status
basis, and every active filter plus the clicked value. A custom window
snaps to the nearest preset and the page says so. Salary buckets drill with
the matching salary floor. Company rows link to the company pages.

## Chart or data table

Every data card carries a small Chart ⇄ Data toggle. The **Data** view is
the card's own table — the same rows the CSV export downloads, one shared
source: if the export says 42, the table says 42. On a narrow window the
table renders its first rows as cards, with **View all** for the full table.
The posting clock's table is its condensed twin (totals per weekday and per
hour plus the peak), not all 168 cells.

## When the market posts

The **When the market posts** card sits in **Demand** and shows the whole
window as a weekday × hour grid — 168 cells, Monday through Sunday down the
rows and hours 00–23 along the columns. All times are **UTC**; the caption
says so and names the busiest cell. The grid shares the page's window,
basis and filters with every other card.

## Copy and export

- **Copy link** puts the page's full URL state on the clipboard — paste it
  to share exactly what you were looking at. It works inside the desktop
  app where the raw clipboard API is unavailable.
- **Export** downloads the combined CSV for every card in the current view
  (pulse, volume, skills, structure, salary and companies), with each card
  under its own section header. Per-card export buttons download that
  card's rows only.

## Reading the numbers honestly

- **One "as of" is not a snapshot.** All cards load in one request and share
  one timestamp, but a source sync landing mid-refresh can be visible to a
  later card; the footer names the as-of time.
- Every card that fails or times out shows an inline error with **Retry**;
  the rest of the tab keeps rendering. A slow card never blanks the page.
- The **coverage** chips in the footer say how much of the window population
  discloses salary and location, how much is linked to a catalog company and
  how much is skill-tagged; **stalled sources are named** beside them.
- Currencies are per-currency on the annualized normalized basis — no FX
  conversion in this release, and thin samples hide the band deliberately.
- Numbers, percentages, dates and currencies render in your locale format.

## Related pages

- [Postings and search](postings-and-search.md) — the live feed every drill
  opens.
- [Companies](companies.md) — the company directory behind the hiring
  cards.
