# Usage

## Find your board slug

The org slug is the segment the employer's board URL is built from:

| Provider | Board URL looks like | API fetched |
|---|---|---|
| Greenhouse | `boards.greenhouse.io/{org}` | `boards-api.greenhouse.io/v1/boards/{org}/jobs?content=true` |
| Lever | `jobs.lever.co/{org}` | `api.lever.co/v0/postings/{org}?mode=json` |
| Ashby | `jobs.ashbyhq.com/{org}` | `api.ashbyhq.com/posting-api/job-board/{org}` |

Open the employer's job page and read the slug out of the address bar —
`boards.greenhouse.io/acme` means org `acme`.

## Add the source

1. Settings → Tools → Connectors → **Add source** → ATS public API.
2. Pick the **provider**, enter the **org slug**.
3. Optional: paste a **partner API token** if the board asks for one.
   It is stored as a secret (never in saved config) and sent as a
   `Bearer` Authorization header.
4. Save and sync.

## Sync behavior

- Rows land as postings with title, company, location, URL and
  publication date; the job URL is the ATS's own hosted link.
- The connector is incremental: unchanged boards answer conditional
  GET with a cheap 304 on the next sync.
- All three API hosts ride the polite runtime's rate cap; the declared
  domain scope covers exactly the three API endpoints — nothing else
  is fetched, redirects off-scope are refused.

## What to be careful at

- **Slug, not company name** — `acme` not `Acme Corp`; a wrong slug is
  the most common empty-sync cause (see Troubleshooting).
- **Public boards only** — if the board hides behind a login, the
  public API has nothing to answer with.
- **One board per source** — three employers means three sources; that
  is what keeps matching, filtering and per-source history clean.
