# Security & Gotchas (authoring)

The trust model as the connector author and the operator experience it.
The user-facing half — what consent means, in plain language — lives at
[Consent, explained](../../user/extension-consent.md); the disclosures
below render **verbatim** from the vendored charter everywhere they
appear (they are data, not copy — never paraphrase them in product
surfaces).

## The trust tiers and what is denied where

| Tier | Runs | Denied | Disclosed residual |
|---|---|---|---|
| T0 declarative | nothing — validated data only | anything executable; unknown nodes/actions never render | rendering is host-side against a closed vocabulary |
| T1 bundled | in-process, reviewed with the product | n/a — reviewed code shipped in the image | the review *is* the control |
| T2 sandbox | one subprocess per extension, capability RPC | every non-allowlisted import; `open`/fs family (`path-denied`); sockets/subprocess/exec (`net-denied`); env writes (`invalid`); `exec`/`compile`/`input` (`unsupported`) | see the residuals below — containment is not trust |
| T3 external | a separate process the app calls | nothing at the perimeter — its sockets are its own; the host governs only returned rows (validated, capped) | the entire perimeter is the residual (disclosed verbatim at consent) |

The load-bearing rule: imported third-party code **never runs
in-process**. Tier is provenance at install (the artifact shape
decides), so a manifest cannot talk its way up the ladder.

## The consent model and the disclosures (verbatim)

Consent is required before any install of imported code/data; it names
capabilities, tier + import class, provenance verbatim, the pinned
digest, and the tier's disclosure. Capability growth, configSchema
changes, tier changes and any code update **re-consent**. The charter
copies, rendered everywhere:

**T3 perimeter (ADR-0040 clause 21):**

> This extension runs as a separate process outside the app's network
> perimeter. It opens its own network connections, with no SSRF guard,
> robots.txt check or rate limiting by the app. The app governs only
> what it returns: outputs are validated and capped.

**T2 sandbox (ADR-0030 clause 2):**

> This extension's code runs sandboxed, not reviewed. Sandboxing limits
> the blast radius of this code; it is not a review of its intent. The
> import is pinned to this exact content digest.

**T0 declarative:**

> This extension is declarative data only: it carries no code, and the
> app renders exactly what it declares — validated against a closed UI
> vocabulary and schema at import. Content stays inside the app's
> rendering and theming; nothing from this extension executes or reaches
> the network on its own.

**'Sandboxed, not reviewed' means what it says**: the sandbox bounds the
blast radius of code the host has NOT reviewed. Do not treat a
sandboxed install as vetted; treat the digest pin + consent record as
the audit trail of what you accepted.

## The secrets law (x-secret)

Connector credentials never live in `job_sources.config`. Fields marked
`"x-secret": true` in the manifest `configSchema` (plus the manifest
`secrets` list) declare **secret slots**; values ride the source's
`secrets` payload and land **at-rest-sealed** in `job_sources.secrets**
(the `ai_providers.api_key_encrypted` discipline). Enforcement, all
sides:

- a plaintext secret inside `config` is a registration-time throw
  (HTTP 400 / `ValidationError`) — never stored, never echoed;
- the admin API returns slot presence and a `…last4` hint only;
- at sync the host decrypts host-side and injects into
  `fetch(config, state, *, transport, secrets)`; a missing slot on a
  credentials-required connector surfaces typed `needs-secret`;
- in T2, the secret value is **structurally unable to cross the seam**
  (no message shape can carry it — the host substitutes
  `{{secret:<slot>}}` placeholders into the next fetch's **headers**
  host-side; URL placeholders are refused typed `invalid`, and the
  response envelope's `finalUrl` plus every error detail cross back
  scrubbed of resolved values — the 2026-10-18 evaluation's H1 policy:
  secrets ride headers only);
- in T3, the config handed to the tool is stripped of declared secret
  slots; the optional transport token resolves host-side.

## Politeness, SSRF and robots (T1/T2 network)

Connectors never open sockets. Everything network-shaped funnels
through the polite runtime (`app/extensions/runtime/http.py` over the
vendored `app/extensions/polite_http.py`):

- **SSRF guard** — resolve-then-connect with the checked address pinned
  into the request (DNS-rebind TOCTOU mitigation), reserved/loopback/
  link-local/private ranges blocked, numeric IPv4 obfuscations coerced
  and checked, **every redirect hop re-validated** and
  declared-domain-scoped.
- **robots.txt** — fetched and cached per host through the same guarded
  transport; a robots 5xx or any failure to obtain a verdict **denies**
  the fetch (fail-closed). This is the remotive story: `Disallow:
  /api/*` ⇒ typed `net-denied` under the default posture; the
  per-deployment escape hatch is an admin decision
  (`CAREER_CONNECTOR_RESPECT_ROBOTS`), never a connector-side bypass.
- **Rate caps** — per-host token buckets sized by each connector's
  declared `max_requests_per_minute` under the global
  `CAREER_CONNECTOR_REQUESTS_PER_MINUTE` ceiling.
- **Conditional GET** — etag/last-modified round-trip through
  `next_state`; 304 means "nothing new", not an error.
- **Retries** — full-jitter backoff on 429/5xx/network errors (60 s
  ceiling), RFC 7231 `Retry-After` honored in both forms; 401/403 fail
  immediately as typed `auth`.
- **Size caps** — response bodies capped in flight
  (`CAREER_CONNECTOR_MAX_RESPONSE_MB`).

The hostile wall (`contracts/polite_http.fixtures.json`, run by
`backend/tests/test_extensions_contract.py`) pins all of this; escape
hatches are Settings (`CAREER_CONNECTOR_*`), never raw environment
reads, and default to the closed posture.

## The sandbox residuals (disclosed, not mitigated)

ADR-0030: containment is not trust — these are the honest edges of the
T2 sandbox:

- **Windows memory posture**: POSIX enforces the address-space cap
  kernel-side in the child's pre-exec; Windows has no pre-exec hook, so
  the memory cap is **not enforced there in v1**. The wall-clock
  watchdog plus call/byte quotas bound damage.
- **Metadata probing**: CPython raises no audit event for
  `os.stat`/`os.lstat`, so metadata probing of guessed paths is not
  denyable at this seam — content access is (the exfiltration-relevant
  surface), metadata shape is not.
- **Startup-loaded modules**: `os`/`sys` load before the import audit
  hook exists; the capability-event wall is their enforcement layer.
- **The daily byte budget** (`CAREER_EXTENSION_SANDBOX_BYTES_PER_DAY`)
  is a process-lifetime bucket — it resets on host restart.
- **Frozen builds**: no interpreter ⇒ T2 self-disables typed
  `unsupported` (capability detection, never a hard dependency).

## The destructive-confirm funnel (D20)

Every chat tool carries exactly one risk class — `read-only |
state-changing | destructive` — declared in the manifest `tools` list
(schema-required) and implemented in code; the registration bridge
cross-checks both directions and throws on any disagreement (an
undeclared implementation, a declared-but-missing one, risk-class
drift). The registry key is the charter namespacing
`<extensionId>:<id>`; the model-facing bind name projects `:` → `__`.

- **read-only** — auto-runs.
- **state-changing** — inert until the user's per-grant enablement
  (`user_tool_grants`, `PUT/DELETE /ai/tools/{key}/grant`, the "Needs
  your enablement" section of the chat tools dialog); without the
  grant the call fails with a typed, model-visible error.
- **destructive** — **cannot execute through `run_tool` at all**. The
  call becomes an ADR-0015 Class-B proposal card (`tool_execution`)
  with a two-step confirm in chat; approval re-validates the tool +
  args at apply time, runs at most once (terminal-first commit), and
  approves that call's stored args — never the tool in general.
  Grants never bypass it (the grant endpoint refuses destructive
  keys). Audit covers both halves: the card row and one
  `ai_generations` row (`tool_run`) per execution.

The user-facing guide to the badges and cards:
[Chat tools, risk badges and approval](../../user/chat-tools-and-approval.md).

## The model never authors this subsystem

No model output may register, enable, schedule or import an extension
or source (ADR-0011 §7 / ADR-0030 §6): source registration and the
desired-state document are admin acts; destructive tool calls become
cards; state-changing ones need grants. When you add a new surface to
this subsystem, keep that boundary — it is charter law
(`modelAuthorship`), not preference.

## Gotchas authors actually hit

- **Manifest rejected at registration/import**: envelope violations
  throw *there*, never mid-run — fix the manifest, not the registry.
  `net` without `domains` is the classic.
- **Ambiguous artifact**: both `extension.py` and `server.py` beside
  the manifest ⇒ typed `invalid` ("ship exactly one entry shape").
- **A 304 is not an error**; returning items on a 304 breaks
  incremental. Equally: stamp the watermark from the rows you actually
  returned.
- **`fixture_payload` emptiness**: the conformance kit runs offline —
  a missing fixture fails the kit, not the runtime.
- **Redirects re-validated**: a board that hops through an
  undeclared CDN host fails `net-denied` even though the final URL is
  in scope — declare every hop's host.
- **Charset/caps**: `raw` is capped (8 KB at T3, validated schema-side
  at T2); trim descriptions deliberately, don't let the cap trim for
  you into an `invalid` row.
