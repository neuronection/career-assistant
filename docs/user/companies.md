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
company with at least one open posting, busiest first, each card with:

- the company name and type badge (public, private, subsidiary,
  non-profit, government, startup — when known),
- headquarters city/country and industry tags (when known),
- the number of open postings and the employee range.

The search box filters by company name.

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
- **Open postings** — every open posting, freshest first, with a direct
  link to the source.

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
