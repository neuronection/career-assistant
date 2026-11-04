# Retrieval operations runbook

This is the operator how-to for the career vector index: where the read and
write surfaces live, how to reindex and cut over a space, how to read a run,
and what to do when a gate or an alert fires. The family contract and its
non-negotiables live in `dev/guidelines/retrieval-ops.md`; this page is the
career runbook, not a second copy of the law.

Everything here is admin-only. The surfaces never expose document, query or
prompt text: counts, ids, scores, reasons, latencies and token usage only.

## 1. Where the surfaces live

| Surface | Route | Role |
|---|---|---|
| Tools → Retrieval | `/settings/tools?section=retrieval` | The write surface: active space, reindex, space lifecycle, maintenance, quality compare, danger zone |
| Audit → Retrieval | `/settings/audit?tab=retrieval&section=overview` | The read-only observation tab: overview, spaces, runs, quality, query health, failures, usage, changes |
| AI activity | `/settings/audit?tab=ai&task=embed` | The raw `ai_generations` ledger for `embed` calls (debugging path) |
| Usage | `/settings/audit?tab=usage` | Embed calls/tokens and the token budget |
| Jobs & runs | `/settings/audit?tab=jobs` | The underlying `background_jobs` rows, including `VECTOR_*` |

The Audit sections are URL-addressable: `?section=overview|spaces|runs|
quality|query-health|failures|usage|changes`. A run, space, golden query or
failure drawer opens with `?detail=<id>`, so an alert can deep-link straight
to the evidence. Nothing in Audit writes; cancel, retry, reindex, compare and
space lifecycle hand off to Tools → Retrieval.

The Retrieval tab is not the AI ledger. Use the AI tab when you need the
embedding prompt or provider error for one call; use Retrieval for the index
state and the run history.

## 2. Reindex by kind, view and since

**Coverage & reindex** on Tools → Retrieval queues one bounded
`VECTOR_RECONCILE` run:

- **Kind** — `posting`, `job`, `profile`, `skill` (all when omitted).
- **View** — `summary`, `requirements`, `responsibilities`, `skills`,
  `body` (all when omitted).
- **Since** — an ISO timestamp; only source rows updated since then.
- **Budget** — embed units for this run (default 2000, max 100000).
- **Limit** — documents per run (default 200, max 5000).
- **Force** — re-embed unchanged content instead of hash-skipping it.
- **Auto-continue** — queue the next bounded batch when this one is partial.

A queued run is reported as queued, never as finished. The action returns
`202` with a run id; the same run is visible in Audit → Runs and in Jobs &
runs. A full reindex is a sequence of bounded runs, not one unbounded scan.
Defaults for batch size (10) and scan limit (500) are for the worker; the UI
normally leaves them alone.

Read the run result from the run drawer (or `GET
/admin/retrieval/runs/{id}`):

| Field | Meaning |
|---|---|
| `scanned` | Source rows inspected in this batch |
| `embedded` | Documents written/updated |
| `skipped` | Unchanged rows hash-skipped (or outside the scope) |
| `failed` | Documents that could not be embedded/indexed |
| `failed_ids` | Up to 500 affected ids; `failed_ids_truncated` says the list was cut |
| `gate` | `pass` / `fail` / `unknown` for the run's own gate evaluation |
| `stage`, `progress` | Worker stage and percentage; not a `run_steps` trace |
| `progress_detail` | Live counters while the run is queued/running: phase, processed/total documents (exact at scan start), cumulative/estimated chunks, embedded/skipped/failed and tokens. Counts only — never ids or text. Pruned when the result commits |
| `heartbeat_at`, `error` | Liveness and the terminal failure reason |

A partial run with `auto_continue` queues its successor. A cancelled run
stops after the current batch; `cancel` sets a flag, it does not rewrite the
run's status.

## 3. Build → backfill → gate → activate → remap → retire/drop

A model or dimension change is a **new space**, never an in-place rewrite.
The active space keeps serving reads throughout.

Each space row persists `space_key` — its cutover identity, stamped once
when the space is created. Activation, the `POSTING_REMAP` payload and the
space status read compare that stored value verbatim; they never recompute
it from the row's current configuration. A later tokenizer/chunker version
therefore cannot silently change a legacy space's identity: migration 0095
stamped every pre-existing row with its v1 key, and the first post-upgrade
cutover still remaps the exact key those semantic mappings recorded.

1. **Build.** Tools → Retrieval → **Spaces** → **Build new** (or `POST
   /admin/retrieval/spaces`). Supply the space name, provider, model,
   dimension, metric and optional prefixes. The space starts `building`; its
   physical index is provisioned off the request path. The active row is
   untouched. A matching build is reused idempotently; a different building
   space with the same name is refused until it is retired or dropped.
   **Token-aware (v2)** is on by default: the form resolves the effective
   embedding profile for the pair (source, exact flag, pinned revision,
   artifact checksum, max input), shows a warning when the selection is the
   labelled fallback, and sends `tokenizer_profile` plus the editable chunk
   bounds (`chunk.max_chunk_tokens`/`overlap_tokens`/`max_chars`). Turning it
   off deliberately submits the legacy v1 char-chunk build. A request that
   supplies a tokenizer without chunk bounds (or the reverse) is refused; the
   server never guesses a tokenizer from a model name and never accepts an
   unavailable artifact. A v2 build pins the profile and chunk budget in its
   space identity; the active v1 space is never re-chunked in place.
2. **Backfill.** Queue reindex runs **against the building space** for every
   kind you intend to serve. Backfill writes through the ordinary bounded
   reconcile writer and stamps coverage snapshots against the building space;
   the active space is not modified. Run until the coverage snapshot is
   current for each kind.
3. **Gate.** Open **Quality** and compare the candidate against the baseline
   (`POST /admin/retrieval/quality/compare`). The versioned golden-query set
   must clear recall ≥ 0.80 and precision ≥ 0.50, and the coverage snapshot
   for every selected kind must be at or above the 99.5% gate. A missing
   golden set is an honest refusal, never a fabricated score.
4. **Activate.** Tools → Retrieval → **Activate** (or `POST
   /admin/retrieval/spaces/{id}/activate`). Activation runs the coverage and
   quality checks again, flips the candidate to `active`, retires the previous
   active space in the same transaction, and enqueues the `POSTING_REMAP`
   invalidation for the retired space key. Manual and terminal mapping rows
   are left alone by the remap handler.
5. **Remap.** The activation response and the Changes section show the remap
   job. Watch it in Audit → Runs / Jobs & runs. Do not retire or drop the old
   space until the remap has settled; reads already follow the new active
   pointer.
6. **Retire and drop.** Retire a non-active space (`POST
   /admin/retrieval/spaces/{id}/retire`, typed name). Drop it after the 7-day
   grace period (`POST /admin/retrieval/spaces/{id}/drop`, typed name; `force`
   skips the grace, not the confirmation). The active space cannot be retired
   or dropped. Dropping removes the physical table and metadata and is
   audited under `vector.space.*`.

If the gate refuses activation, the `409` body carries
`activation_gate.reasons`: `coverage_fail` means one or more kinds are below
the coverage gate (backfill them); `quality_below_floor` means the compare
missed recall/precision (inspect the per-query misses in Quality and fix the
content, views or golden set, then re-compare). Never lower the floor to force
a cutover.

## 4. Embedding tokenizer profiles (plan 52 T2a/T2b)

The **Tokenizer & limits** card on Tools → Retrieval owns the embedding
model's tokenizer/limit profile. Resolution is deterministic and keyed on
**provider class + model id**, never on a model-name substring:

1. **admin** — an `embedding_model_profiles` row (explicit override);
2. **curated** — the code catalog in `app/ai/tokenizers/registry.py`:
   the three OpenAI embeddings (`text-embedding-3-small`,
   `text-embedding-3-large`, `text-embedding-ada-002` → bundled
   `cl100k_base`) plus verified open-source families with pinned Hugging
   Face `tokenizer.json` provenance (nomic, mxbai, bge, Qwen3-Embedding,
   multilingual-e5);
3. **fallback** — the conservative UTF-8/codepoint heuristic, always
   `exact=False`.

A known model served by another provider class is **fallback**, and no
profile is guessed from a model-name substring. Curated open-source rows
carry their repository, 40-character revision, artifact SHA-256, license and
source URL; the API and card show them. A family whose repository is gated or
whose tokenizer cannot be fetched honestly (currently `embeddinggemma`) is
listed as an **unavailable preset** and stays visibly on the fallback — it
never claims support. The card and the build-space form preview show the
source, exact flag, availability, max input tokens, per-request batch limits
and the default token chunk budget; a fallback or unfetched asset is called
out with a warning before the space is built.

### Hugging Face tokenizer fetch (plan 52 T2b)

An admin may pin a Hugging Face repository, a full 40-character commit
revision and the `tokenizer.json` SHA-256. The fetch is a bounded
`tokenizer_fetch` background job, never a request/boot read: host allowlist
(`huggingface.co` + its CDN/Xet hosts), small-file allowlist
(`tokenizer.json` + optional `config.json`/`tokenizer_config.json`/
`special_tokens_map.json`), 32 MiB artifact cap, redirect validation, no
`trust_remote_code`, and SHA-256 verification. The artifact is cached at
`<data_dir>/tokenizers/<sha256>/tokenizer.json`, so a repeat is a cache hit
with no network. Desktop/offline installs use the cache/bundled assets only;
a missing/corrupt asset degrades to the labelled heuristic, never fake
exactness. Selection changes stay `vector.model.changed`; fetch jobs audit
`vector.tokenizer.fetch_requested`, `vector.tokenizer.fetched` and
`vector.tokenizer.fetch_failed`.

Admin endpoints (admin-only, aggregates only, no raw text):

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/admin/retrieval/model-profiles` | curated catalog, admin overrides and the assigned model's effective profile |
| `GET` | `/api/v1/admin/retrieval/model-profiles?provider=<type>&model=<id>` | preview the resolution for a build-space pair |
| `PUT` | `/api/v1/admin/retrieval/model-profiles` | save one bounded override (tiktoken/HF/heuristic, identifier/revision/checksum, max input, batch items/tokens, chunk tokens/overlap/chars) |
| `DELETE` | `/api/v1/admin/retrieval/model-profiles?provider=<type>&model=<id>` | remove the override; curated/fallback returns |
| `POST` | `/api/v1/admin/retrieval/tokenizer/fetch` | queue one pinned HF fetch (repo, 40-char commit, allowlisted files, optional expected SHA-256); idempotent and audited |
| `GET` | `/api/v1/admin/retrieval/tokenizer/fetch/{job_id}` | fetch job status/progress/result (admin-only; no text) |

Validation happens at the domain boundary: the tokenizer contract owns the
exact/fallback law, the chunk budget must fit the model input and one batch,
`chunk_max_tokens >= 32`, `overlap * 2 < max_chunk_tokens`, and this build
accepts the bundled `tiktoken` (`cl100k_base`), a pinned
`hf_tokenizers` selection (repository + 40-character commit + artifact
SHA-256) or the `heuristic` kind; `sentencepiece` stays reserved. Unknown or
out-of-range input answers `400`/`422`. Changes are audited as
`vector.model.changed` with a `model_profile:<provider-class>/<model>`
resource — the existing group, no second ledger.

**It is configuration, not a rewrite.** Saving a profile does not rechunk,
re-embed, re-key or cut over any space; an existing space keeps exactly the
chunker it was built with.

### Token-aware build and cutover (plan 52 T3b/T3c)

The **Build new space** dialog (and `POST /admin/retrieval/spaces`) accepts a
v2 identity in two additive forms:

- `tokenizer_profile: {provider, model}` — the server resolves the same
  effective profile the write path uses (admin → curated → fallback, HF
  included) and pins that tokenizer; `chunk` optionally overrides the
  profile's default budget.
- `tokenizer: {kind, identifier, revision, artifact_sha256, exact,
  max_input_tokens, source}` plus `chunk: {max_chunk_tokens, overlap_tokens,
  max_chars}` — an explicit pin. A non-heuristic artifact must be loadable in
  this instance; the API refuses an unavailable one rather than silently
  degrading.

Omitting both (and `chunk`) keeps the legacy v1 build. Supplying only one
half is a `400`, as is a chunk budget that cannot fit the model input. The
server persists the tokenizer/chunk identity plus the selection source
(migration `0097`; source is provenance, not part of the frozen space key).
The space key itself remains the stored v1 or v2 pre-image and is never
recomputed at cutover.

The **Tokenizer & limits** report reads the active space's persisted chunker:
a v2 space reports `chunking.token_aware: true` with its token budget; a
legacy active space (or no active space) reports the v1 char chunker and
`token_aware: false`. Spaces, runs and the Audit drawers carry the same
`token_aware`/`tokenizer`/`chunk` evidence and a runbook link. A fallback or
approximate tokenizer is labelled everywhere; nothing claims exactness it
does not have.

## 5. Maintenance actions

**Index maintenance** on Tools → Retrieval queues one typed
`VECTOR_MAINTENANCE` run. Each action is bounded and returns the normal run
result.

| Action | What it does |
|---|---|
| **Index rebuild** | PostgreSQL `REINDEX INDEX CONCURRENTLY` on the space's HNSW index, on an AUTOCOMMIT connection. SQLite has no online rebuild for `vec0`, so it runs `VACUUM` and says so. A linear desktop space skips the physical action honestly. |
| **Vacuum** | PostgreSQL `VACUUM (ANALYZE)` / SQLite `VACUUM`, both on AUTOCOMMIT. |
| **Orphan sweep** | Pages the space's documents and deletes those whose polymorphic source no longer resolves. Dry run counts without deleting. Default limit 500, max 5000. |
| **Retry failed** | Takes the failed ids from the latest failed run and re-enqueues a scoped reconcile for exactly those documents. Dry run previews the count. With no recorded failures it refuses (`409`) instead of scanning the corpus. |

Maintenance never runs DDL on the request path. The physical action is a
`background_jobs` row, visible in Audit → Runs.

## 6. Idempotency, locks and crash recovery

- **Idempotency key.** Every mutating action requires an
  `Idempotency-Key` header (8–120 characters) or the equivalent body field.
  Replaying the same key with the same body within 24 hours returns the
  original run; the same key with a different body is a `409`. The UI
  generates a fresh key per click.
- **One active run per space.** `VECTOR_*` runs take `lock_key =
  vector_space:<space_id>`; a partial unique index over queued/running rows
  enforces it at the database. A second reindex, cutover or activation for
  the same space is refused (`409`) while the lock is held. A build holds the
  space-name lock until the building row has an id.
- **Stale heartbeat.** Workers write `heartbeat_at` every 30 seconds. A
  reaper runs every 60 seconds and fails a running vector run with no
  heartbeat for 15 minutes as `stalled: no heartbeat for 15m`, releases the
  lock, writes `vector.run.stalled`, and lets the next action proceed.
  `recover_orphans` at boot is a second path, not the only one.
- **Retry** re-enqueues a terminal run with its preserved scope under a fresh
  idempotency scope. Cutover/gate evaluations are synchronous and cannot be
  retried as runs; re-run the action instead.

## 7. Alerts, dedup and recovery

Retrieval alerts go through the existing notification funnel only. All ten
kinds are boot-seeded; an unknown or disabled kind fails soft and notifies
nobody. Each is admin-scoped, deduped and recovery-reset.

| Kind | Fires when | Dedup | Manage URL |
|---|---|---|---|
| `retrieval.coverage_low` | Coverage below the 99.5% gate with no active building run | `space` | `/settings/tools?section=retrieval` |
| `retrieval.reindex_failed` | A `VECTOR_*` run reaches terminal `failed` | `space+kind` | `/settings/audit?tab=retrieval&section=runs&detail=<run_id>` |
| `retrieval.reindex_stalled` | A non-terminal run has no heartbeat/progress for 15 min | `run_id` | `/settings/audit?tab=retrieval&section=runs&detail=<run_id>` |
| `retrieval.quality_gate` | The golden-query compare misses recall 0.80 or precision 0.50 | `space` | `/settings/audit?tab=retrieval&section=quality` |
| `retrieval.query_slo` | Query p95 > 1500 ms for 15 min | `space` | `/settings/audit?tab=retrieval&section=query-health` |
| `retrieval.degraded_rate` | Degraded share > 5% over 15 min | `space+reason` | `/settings/audit?tab=retrieval&section=query-health` |
| `retrieval.provider_unassigned` | The embeddings task has no provider/model assignment | `singleton` | `/settings/tools?section=retrieval` |
| `retrieval.index_missing` | The pgvector extension or index is absent on web | `space` | `/settings/tools?section=retrieval` |
| `retrieval.budget_exhausted` | `AIBudget(task_type='embed')` is exhausted | `window` | `/settings/audit?tab=retrieval&section=usage` |
| `retrieval.space_drop_pending` | A retired space is past the 7-day grace | `space` | `/settings/tools?section=retrieval` |

A condition that clears releases its dedup key, so a later recurrence
notifies again; a still-true condition is not repeated inside the dedup
window. Daily caps are per channel. The evaluator is the bounded
`retrieval_alert_sweep` system job on a five-minute schedule; it reads the
latest snapshots, recent runs, 15-minute rollups, the persisted quality
compare and the token budget, never the corpus.

## 8. Honest degraded and cold states

- A space that has never been reconciled says **never reconciled**. It does
  not show a fake 0% or 100%.
- ANN recall is **not sampled** until the maintenance probe runs. That is a
  real state, not a failure.
- An empty install or a space with no golden set reports `empty` /
  `no_golden_set` rather than inventing numbers.
- A degraded query was served from the lexical fallback. Query health shows
  the reason: `provider_unassigned`, `embed_failed`, `index_missing`,
  `space_mismatch` or `over_cap`.
- The backend label is honest everywhere: PostgreSQL pgvector/HNSW, SQLite
  sqlite-vec, or “Linear fallback — desktop scale”. Unsupported maintenance
  actions are skipped with a reason, never faked.
- No raw text rule: Retrieval DTOs, exports and alert payloads carry no
  document, query or prompt text. Raw embed text stays on the admin AI tab;
  the status export is aggregates only.

## 9. Troubleshooting

### Is this posting indexed?

Two ways to answer the same question, both admin-only and aggregate-only:

- Open the posting's detail page — under its facts an admin sees one line
  with the state, the space facts (`name · model · dim · backend`) and the
  record count, linking to Tools → Retrieval.
- Or call `GET /api/v1/admin/retrieval/documents/status?kind=posting&source_ids=<uuid>`
  (repeatable or comma-joined; at most 50 ids — an empty list or more is a
  400, never a silent truncation). `kind` is one of `posting`, `job`,
  `skill`, `profile`.

The read composes the existing document, record and source rows at request
time; nothing is stored or backfilled. The five states:

| State | Reason | Meaning |
|---|---|---|
| `current` | — | Document exists, schema version matches, source hash matches, record count matches. |
| `stale` | `schema_version_mismatch` / `source_hash_mismatch` | Indexed, but the composer version or the composed text changed since the write — reindex that source. |
| `missing` | `document_missing` / `source_unavailable` | No document in the active space, or the source row itself is gone. |
| `incomplete` | `no_records` / `record_count_mismatch` | The document exists but its records are missing or fewer than the composer would write (lost chunks); reindex. |
| `off` | `no_active_space` | No active content space, so nothing is indexed. Cold is not zero — build and activate a space first. |

None of these states gates serving: an unindexed posting is fully returned,
and the semantic paths degrade to the lexical order. That is ADR-0051 §7
(the family vector-retrieval ADR in the dev repo) — semantic is a ranking
signal, never a gate.

| Symptom | Check | Fix |
|---|---|---|
| **No provider / embeddings unassigned** (`retrieval.provider_unassigned`) | Settings → AI → Tasks: the embeddings slot | Assign an embeddings-capable model, then reindex. A fresh install answers 503 until configured. |
| **Missing index** (`retrieval.index_missing`) | Overview/health backend label; PostgreSQL extension | Run **Index rebuild**; confirm `CREATE EXTENSION vector` on web. On SQLite/linear the label explains the fallback. |
| **Activation refused** (`409`, `coverage_fail` / `quality_below_floor`) | The `activation_gate` block and the Quality misses | Backfill the missing kinds; fix content/views/golden set; re-run compare. Both gates must pass. |
| **No golden set** (`no_golden_set`) | Quality section | Ship the versioned golden-query fixture for the space; activation cannot proceed without it. |
| **Stale run** (`retrieval.reindex_stalled`) | Run drawer heartbeat; Jobs & runs | Wait for the 15-minute reaper (it fails the run and releases the lock), or cancel; then retry. Check the worker is alive. |
| **Queued but nothing moves** | Audit → Jobs & runs; scheduler/worker health | Confirm the worker and `retrieval_alert_sweep` are running; cancel and retry if the row is wedged. |
| **Another run holds the space** (`409`) | Audit → Runs (queued/running for the space) | Wait for it, or cancel it, then retry. One active run per space is intentional. |
| **Idempotency replay mismatch** (`409`) | The key and body | Use a new key for a different request; replay the same key+body to read the original result. |
| **Budget exhausted** (`retrieval.budget_exhausted`) | Audit → Usage: embed tokens vs `AIBudget(task_type='embed')` | Wait for the next budget window or raise the embed budget; the per-run **Budget** field caps a single reindex separately. |
| **Degraded queries** (`retrieval.degraded_rate`) | Query health reasons | Fix the named cause (assignment, index, space mismatch, cap); lexical fallback is expected while degraded. |
| **403/404 on a surface** | Admin session | Retrieval is instance-admin only; the desktop owner is admin by first-user provisioning. |
| **Desktop: `database is locked` from `semantic_rescue`** | Backend log: `sqlite3.OperationalError: database is locked` at a `vector_documents` INSERT, ~30s after startup | The vector store commits through its own connection and SQLite has one writer; the inline index now releases the caller's transaction before indexing **and again after the embed** (the gateway audits by flushing an `ai_generations` row into the same session, which re-takes the lock) — plans 192/194. If it still appears, check for another long-running writer (an import or a raw `sqlite3` session) and restart. |

After any fix, re-run the smallest scoped action that proves it (one kind or
one view), read the run result, then widen the scope. Record the run id and
the audit event in the incident note; the Changes section already has the
`vector.*` trail.

## 10. Plan 52 handoff (T2b / T3)

**T2b — provider/HF fetch and a wider curated catalog (implemented).**

- The pinned, checksum-verified `tokenizer_fetch` job loads only an
  allowlisted `tokenizer.json` (+ small config) from `huggingface.co` and its
  CDN/Xet hosts at a full 40-character commit revision; it is bounded,
  audited and cached by content hash. No request/boot path fetches.
- `hf_tokenizers` loads the verified local cache and exposes count/encode/
  decode; a missing/corrupt artifact degrades visibly. `sentencepiece` stays
  reserved.
- Curated open-source profiles (nomic, mxbai, bge, Qwen3-Embedding,
  multilingual-e5) carry repository/revision/SHA-256/license/source URL;
  `embeddinggemma` is listed as an unavailable gated preset. Unknown models
  stay fallback.
- The admin editor supports the HF kind, fetch action/status and the
  provenance/availability warnings. Curated rows remain code facts (no
  migration invents model data).
- T3a stores each space's v1 key on the row (`vector_spaces.space_key`,
  migration 0095) and every cutover comparison reads it verbatim; T3b still
  owns token-aware writes, `space_key` v2 and the cutover that consumes them.

**T3b — token-aware chunk writes and cutover (backend/contract/schema implemented).**

- The contract now has a v2 identity: `VectorSpace.tokenizer` + `VectorSpace.chunk`
  are both-or-neither, `space_key_v2` folds the tokenizer
  kind/identifier/revision/artifact sha/exact and the
  `ChunkConfig.fingerprint` after a version marker, and `space_key` keeps
  the frozen v1 pre-image. A stored key always wins; a legacy row is never
  re-keyed. `IndexRecord` carries optional
  `token_count`/`token_start`/`token_end` (ordered, non-negative,
  `count == end - start`).
- Migration `0096` adds the tokenizer/chunk scalars to `vector_spaces`
  (all NULL on a v1 row; a v2 row requires the complete set,
  `chunker_version='2'`, a kind-valid exact/revision/checksum combination
  and a chunk budget that fits the input limit) and the nullable token
  offsets to `vector_records`. Downgrade drops the columns but keeps the
  stored `space_key`.
- `vector_index_service` resolves the **effective DB profile** (admin →
  curated → fallback, HF included) for write/build paths and token
  accounting. A v2 space composes every embeddable view (summary,
  requirements, responsibilities, skills, body) with the token chunker:
  exact character offsets, token overlap, `max_chars` as a ceiling, the
  document prefix + safety margin inside `max_input_tokens`. Batches split
  by both `batch_max_items` and `batch_max_tokens`; an item that cannot fit
  is a typed `input_too_long` write failure recorded once by reconcile,
  never a loop or truncation.
- A v1 active space keeps the char chunker, NULL token columns and is never
  re-chunked in place. Build a v2 space beside it
  (`scripts/vector_spaces.py build --token-aware`, or the lifecycle/action
  service with an explicit tokenizer+chunk), backfill, activate through the
  existing coverage/quality gate, and the retired row's stored key drives
  `POSTING_REMAP`; the old space is retained.

**T3c — build/cutover UI, API contract and reports (implemented).**

- `BuildSpaceRequest` accepts `tokenizer_profile` or an explicit
  `tokenizer` + `chunk`; the OpenAPI contract and generated client carry the
  same fields. Omitted fields keep the v1 build; a half-configured request,
  an unavailable artifact or an unsafe chunk budget is refused.
- Tools → Retrieval shows the resolved profile (source, exact/approx,
  revision, checksum, max input), warns on the fallback, lets the admin edit
  the chunk bounds and submits a v2 build (or a deliberate legacy v1 build).
- `SpaceDTO` / `RunDTO` expose `token_aware`, `tokenizer` and `chunk`; the
  Tools space card, Audit space drawer and Audit run drawer render them with
  the existing live progress counters and a runbook link. No Audit action
  controls were added.
- Migration `0097` persists the tokenizer selection source. A legacy active
  space still reports v1/legacy; only a space with persisted tokenizer columns
  may claim `token_aware: true`.
- The old space is retained through the normal retire/drop lifecycle. Nothing
  is re-chunked in place.

**T5 handoff (Study parity + rollout).**

- Port the same tokenizer registry, chunk identity and `space_key_v2` to
  Study; replace its `len//4` token heuristic and add DTO/fixture parity.
- Roll out a candidate space on real corpora: backfill, compare coverage and
  the golden-query quality gate, activate, confirm the `POSTING_REMAP` for the
  retired stored key, and keep the old space until an explicit drop.
- Add the fallback/tokenizer-missing alert and the fleet docs pointer. HF
  auto-fetch and SentencePiece remain last, not prerequisites.
