# Service-layer sizes — career-assistant

Ledger for the family service-cohesion law (family plan 40; band edge ~780,
soft trigger ~800, per-repo glob `backend/app/services/**/*.py`). One row per
file over the band at the 2026-10-25 re-measurement, in the plan-40 W0 format
(`| path | lines (dated) | accept | decline (dated, reason) |`). W3 is a
record-and-adjudicate pass — nothing was restructured; a decline is dated and
re-proposes on the file's next touching round or on >20% growth past the
recorded size (plan-40 clause 4).

| path (as measured 2026-10-25) | lines (dated) | accept | decline (dated, reason) |
|---|---|---|---|
| `cv/cv_renderer.py` | 1,450 (2026-10-25) | accepted 2026-10-25 (plan 40 W3): the deterministic render path — one pure pipeline (template + snapshot + options → print-ready HTML + layout metrics); page estimation, escaping and CSS emission are facets of the one render contract, with no CRUD, AI or HTTP fused in | — |
| `postings/explore_service.py` | 1,102 (2026-10-25) | accepted 2026-10-25 (plan 40 W3): the unified filter/facet engine — filter parsing, SQL condition building, keyset/ranked pagination and self-excluding facets are stages of one query pipeline; the size tracks the filter-dimension count, not fused domains | — |
| `postings/postings_service.py` | 996 (2026-10-25) | — | declined 2026-10-25 (plan 40 W3): its own docstring names the fusion — connector sync, skill-ID mapping, fit scoring, listings, interactions, alerts, expiry as one flat module; each has a clean seam (future `postings/sync.py` · `mapping.py` · `fit.py` + state/alerts siblings, per the repo's own packaging reference shape). Re-propose on touch or +20% growth past 996 |
| `cv/cv_synth_service.py` | 972 (2026-10-25) | accepted 2026-10-25 (plan 40 W3): one aggregate (`CvSynthItem`) and its policy engine — CRUD, gateway-mediated generation and match/apply are operations of the same variant lifecycle (activation-supersedes, evidence refs); ~800 of the lines are a single class | — |
| `cv/cv_intake_service.py` | 927 (2026-10-25) | accepted 2026-10-25 (plan 40 W3): one intake flow — parse → draft → review-first apply over the `CvParseDraft` aggregate with per-row provenance; the apply halves share the selection semantics and dedupe rules, so no seam without coupling the flow | — |
| `job_worker.py` | 912 (2026-10-25) | — | declined 2026-10-25 (plan 40 W3): the durable queue machinery (claim/retry, ~260 lines) fused with ~20 per-kind handler adapters drawn from every domain in one flat file — also the only over-band file outside a `services/<domain>/` package; a `job_worker/` package (queue + per-family handler modules) is the right future, and every new job kind touches this file, so the trigger fires often. Re-propose on next touch (any new job kind) or +20% growth past 912. Re-touched 2026-11-02 (plan 153 slice 1: the `embeddings_reconcile` handler, ~970 lines) — split still declined, same seam: the reconcile is one more 10-line adapter; the queue/handler split stays the right future, re-propose on the next job-kind touch |
| `vector_reconcile_service.py` | 861 (2026-11-04) | accepted 2026-11-04 (plan 52 T4): one resumable scan contract — keyset paging, compose/hash classification, budget caps, coverage snapshots and the carried live-progress counters are stages of the same pass; the growth is the T4 counter/carry path, not a second domain | — |
| `cv/cv_export_service.py` | 852 (2026-10-25) | accepted 2026-10-25 (plan 40 W3): an exporter with one job — compile the current state into an immutable version, then serialize (md / ats_text / docx / json are pure payload functions) plus the ATS lint gate; PDF already lives in its own `cv_pdf_service` | — |

W3 resolution (2026-10-25): 7 over-band files — 5 accepted as single-concern
cohesion, 2 declined with dated triggers. No code moved; the declines seed
future rounds, not this one.
