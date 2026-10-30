# Companies

The Companies section is the employer side of the job catalog: every
company that currently has open postings, with reviewed facts, financial
claims that carry their sources, and all of that company's open postings
on one page.

> Company facts are **reviewed data, not scraped guesses**. What the
> postings prove (hiring volume, seniority mix, work modes, locations)
> is derived live from the connected sources; descriptive facts
> (industry, size, headquarters, financials) are entered and reviewed by
> your instance's admins. Anything nobody knows stays explicitly
> "unknown" — the app never fills gaps with invented numbers.

## Browsing companies

Open **Companies** from the sidebar (`/companies`). The list shows every
company with at least one open posting, busiest first, each card in the
app's item-card grammar:

- the company's org tile and name (the whole card opens the company
  page),
- labeled spec facts — company type, employee range, founding year
  (when known) — plus headquarters and website domain,
- industry tags and the number of open postings.

Filter by the hiring the companies are doing right now (plan 154): a
filter rail over the **active postings** — work mode, seniority,
employment type and industries as tri-state chips with live counts
("12 companies hiring remote"), plus a location box and a minimum
open-roles floor. The chips reuse the Explore filter language; the
counts recompute as you filter. The search box filters by company
name; the **New** filter narrows the
list to posting-born companies (created from a job post and not yet
reviewed — they carry a New badge until an admin promotes them).

## The company page

Open a company to see everything about it in one place:

- **Facts** — headquarters, employee range, founding year, industry,
  website, and a short description.
- **Financials** — one card per claim (revenue, valuation, market cap,
  funding raised, net worth) with the amount, the **as-of date** and the
  **source** it came from. A claim without a source is worth exactly
  nothing, so the app always shows where a number came from.
- **Hiring signal** — derived from the live postings: seniority mix,
  work-mode split (on-site / hybrid / remote) and the top locations.
  This section reflects what the company is doing right now, not what
  someone wrote about it last year.
- **Open postings** — every open posting as the **same card the live feed
  uses**: fit bubble, requirement-ordered skills, and the same actions
  (apply, save, hide — applied/saved state stays in sync with
  `/postings`). The card opens the posting's in-app page
  (`/postings/:ref`); the source-board link is the card's Apply action.

## Where the data comes from

Postings flow in through the connectors your admin configured
([Add a job source](add-a-job-source.md)); each posting's employer is
normalized to one company entry, so "ACME GmbH", "ACME" and "Acme Cloud
Ltd" are one company, not three. Admins maintain the reviewed facts
through the admin API (`PUT /api/v1/admin/companies/{key}` — an in-app
settings surface is planned); when two company entries are merged, a
moved profile is flagged for review rather than silently combined.

## Related

- [Postings and search](postings-and-search.md) — the live feed and
  Explore filters these postings also appear in.
- [Matching and rankings](matching-and-rankings.md) — how postings from
  these companies are scored against your profile.

## How names become companies

Job postings spell the same employer many ways. The matcher resolves
each label to one canonical company — exact keys (slug, known alias,
initialism like `P&G`, the posting's ATS domain) first, then a
conservative fuzzy score. Junk labels ("Confidential", staffing
agencies) never create companies, and only strong evidence links
without review. Everything the matcher learns is visible and editable
under **Companies rules** (`/settings/companies`): aliases, never-link
exclusions, the pending near-miss queue, merge suggestions and the
matcher thresholds.

New companies start as **New** (proposed) and appear in this list as
soon as they have a live posting — they graduate to established when
the evidence is strong (a matching company domain, an arbitrated match,
or postings from two or more sources), or when an admin promotes them.
