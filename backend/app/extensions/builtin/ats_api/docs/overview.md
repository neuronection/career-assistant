# ATS public API (Greenhouse / Lever / Ashby)

One bundled connector, three public applicant-tracking boards: read a
company's public job board straight from its ATS — Greenhouse, Lever or
Ashby — with one config pair (provider + org slug) and no account.

- **Public APIs, polite runtime.** Requests ride the app's polite
  transport: conditional GET (ETag/Last-Modified) cached, a per-host
  rate cap, and the declared domain scope enforced on every hop —
  `boards-api.greenhouse.io`, `api.lever.co`, `api.ashbyhq.com`.
- **Token optional.** Public boards need nothing. Boards on a partner
  tier accept an optional bearer token — stored in the app's secret
  store, never in config.
- **One board per source.** The provider and org slug pick exactly one
  board; three employers are three sources.

## When to use it

You follow a specific employer that publishes its openings on
Greenhouse, Lever or Ashby and want the board kept in sync on your
schedule — filtered, matched and explained like every other source.

## When NOT to use it

Aggregated multi-company boards (Arbeitnow, Remotive, Jobicy cover
those), a single posting you already have the URL for (paste it — the
manual-URL connector), or a private/internal board that requires real
authentication (the optional token is a partner-tier aid, not a login).
