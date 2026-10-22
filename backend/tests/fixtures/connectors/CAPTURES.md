# Captured connector truth

Every fixture in this directory is a snapshot of a **real** response,
captured on the date noted. Tests never open a socket: the polite runtime is
driven over `httpx.MockTransport` with an injected resolver. Trimmed arrays
keep the captured item shape verbatim; no field was invented.

| Fixture | Captured | Source |
|---|---|---|
| `arbeitnow_job_board.json` | 2026-10-17 | `https://www.arbeitnow.com/api/job-board-api` |
| `remotive_remote_jobs.json` | 2026-10-17 | `https://remotive.com/api/remote-jobs` |
| `jobicy_remote_jobs.json` | 2026-10-17 | `https://jobicy.com/api/v2/remote-jobs` |
| `robots_remotive_com.txt` | 2026-10-17 | `https://remotive.com/robots.txt` |
| `personio_jobs.xml` | 2026-10-22 | `https://personio-gmbh.jobs.personio.de/xml` (3 real positions; description bodies trimmed) |
| `join_com_jobs.json` | 2026-10-22 | `https://join.com/api/public/companies/54/jobs?pageSize=5&page=1` (first 3 items + real pagination) |
| `recruitee_offers.json` | 2026-10-22 | `https://bunq.recruitee.com/api/offers/` (first 3 offers; long descriptions trimmed) |
| `teamtailor_jobs.json` | 2026-10-22 | `https://career.teamtailor.com/jobs.json` (first 2 items; HTML bodies trimmed) |
| `stepstone_xing_jobs.xml` | 2026-10-22 | `https://weworkremotely.com/categories/remote-programming-jobs.rss` — the RSS 2.0 wire shape StepStone/Xing job-alert feeds use (neither board publishes an anonymous feed; the connector consumes the signed-in alert URL) |
| `salary_samples.json` | 2026-10-22 | DACH posting salary strings (`52.000 - 65.000 €`, `CHF 90'000`, …) plus the existing USD formats |

Wire notes worth keeping:

- Personio's feed is XML (`<workzag-jobs><position>`); descriptions are
  nested `<jobDescriptions><jobDescription><name/><value/>`; no salary field.
- JOIN returns salary amounts in **minor units** (`9000000` = €90 000) and
  caps `pageSize` at 5.
- Recruitee uses naive `"YYYY-MM-DD HH:MM:SS UTC"` timestamps.
- Teamtailor is JSON Feed 1.1 with an embedded schema.org `_jobposting`.
- RSS 2.0 `pubDate` is RFC 822, not ISO.
