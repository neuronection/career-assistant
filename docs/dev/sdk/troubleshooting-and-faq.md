# Troubleshooting & FAQ (developer diagnostics)

Every failure mode this subsystem's own test walls exercise, decoded —
if a test pins it, an operator can hit it. The user-facing decoder for
source/extension symptoms lives at
[Extension troubleshooting](../../user/extension-troubleshooting.md).
Error codes are the closed 15-code enum in the
[Reference](reference.md#error-codes).

## Symptom → cause → fix

### Sources and imports

| Symptom | Cause | Fix |
|---|---|---|
| `source sync` reports `invalid: no extension manifests found (root + one level scanned)` | discovery scans the subpath + one level only; the manifests sit deeper | move the extension dir up one level, or set the descriptor's `subpath` to its parent |
| `invalid: manifest invalid: …` at sync | the manifest fails the vendored envelope schema (missing required field, bad shape) | fix the manifest; `source validate <path-or-url>` runs the same checks read-only |
| `unsupported: kind … is not hosted for import` / `capabilities not honored for a T3 import` | host-profile rejection with reason rendered | align the manifest with the profile (T3 ⊆ `{sync, secrets}`; T2 ⊆ `{sync, net, state, secrets}`) or ship it to a host that honors it |
| `unsupported: requires host connector refinement >= 2 (host has 1)` | manifest `kindVersion` newer than the host | upgrade the host or lower the manifest's `kindVersion` (see [Versioning](versioning-and-migration.md)) |
| `unsupported: no runnable entry beside the manifest (expected extension.py … or server.py …)` | connector artifact has no entry — or has both (ambiguous ⇒ `invalid`) | ship exactly one entry shape |
| `path-denied: local extension sources are gated off in production boots` | `CAREER_APP_ENV=production` rejects the `local` kind, fail-closed | use an https git source in production; keep local sources to dev |
| `path-denied: local source … is outside every allowlisted root` | the repo root doesn't resolve under `CAREER_EXTENSION_LOCAL_SOURCE_ROOTS` | add the parent dir (JSON list) and re-add the source |
| `invalid: a source descriptor carrying an inline token…` (schema seam) | private-repo credentials must be sealed slot references | send credential values through the admin API `secrets` payload or the settings UI — never in the descriptor |
| Source `failing`, install pins untouched, update note `lastCheckFailed: true` | a failed fetch never refetches or moves pins (D22) | fix the fetch (network, ref, credentials), re-sync |
| Install update state `digest-drift`, source `degraded` | the same pinned ref now yields different content — the supply-chain attack signal | verify the upstream (tag moved? history rewritten?), then re-consent explicitly (`source pin <id> --consent` applies the recorded update after a fresh check) |
| Update stuck `available`/`requiresReconsent` | there is no auto-apply path — by design | apply it: `source pin <extension-id> --consent` (or the apply API) |
| Reconcile reports `needsConsent` for a desired extension | the list is a pin-mover; consent is the gate | consent once at that digest through the consent surface, then reconcile installs it |
| Reconcile reports `ignoredEnableIntent` | reconcile never auto-enables (D22) — the `enabled` field is acknowledged and ignored | enable the instance explicitly (admin UI/API) |
| Reconcile reports `drift: manually installed` | manual installs are never re-pinned or removed by the list | move the extension to gitops management (re-import managed-by gitops) or keep managing it manually |

### Sync and the transport

| Symptom | Cause | Fix |
|---|---|---|
| `net-denied` on Remotive syncs under the default posture | `remotive.com/robots.txt` carries `Disallow: /api/*`; robots law is fail-closed (the fixture wall pins exactly this) | an operator who judges the use consistent with Remotive's API terms lifts it per deployment: `CAREER_CONNECTOR_RESPECT_ROBOTS=false` — a deliberate admin decision, never a connector-side bypass |
| `net-denied` on a redirect chain that "should" pass | every hop is re-validated against the declared domains — an undeclared CDN host fails | declare every hop's host in `domains` |
| `not-ready: no transport injected` | a connector was called without the runtime (direct call in code/tests) | treat transport as required — fail closed, never return empty success |
| `rate-limited` with `retry_after_ms` | upstream 429; the runtime honored Retry-After | nothing to fix — the next sync backs off; lower the connector's `max_requests_per_minute` if it recurs |
| `needs-secret: missing secret slot(s): …` | credentials-required source with an unfilled slot | fill the slot in Settings (sealed payload); `***` preserves, empty clears |
| `invalid: Secret … never lives in config` | a plaintext secret was sent inside `config` (registration-time throw, HTTP 400) | send it via the source's `secrets` payload only |
| 304 "no rows" confusion | conditional GET says nothing changed — not an error | nothing to fix; it is the incremental contract working |

### The T3 script tier

| Symptom | Cause | Fix |
|---|---|---|
| The `mcp` connector is missing from the catalog | the script tier is off by default: invisible until allowlisted | `CAREER_CONNECTOR_PLUGINS_ALLOWLIST='["mcp"]'` (admin opt-in) |
| `not-ready: the mcp connector is not allowlisted…` at install time | T3 import tried while the tier is off | allowlist `mcp` first, then install |
| `protocol: tool output is not the {items, next_state} envelope` | the tool's first text block must be the envelope JSON | return exactly `{"items": [...], "next_state": {...}}` |
| `invalid: N row(s) beyond the 300-item cap dropped` / `raw exceeds size cap` | app-side row caps (300 items, 8 KB `raw`/`next_state`) | page/batch your fetches across syncs; keep `raw` small |
| `unreachable` after ~30 s; other sources kept syncing | tool timeout (5–120 s, default 30) fails its own source only | raise `timeout_seconds` for slow sources or make the tool faster |
| `invalid` rows dropped at the seam | rows failed `RawPosting` validation (missing `external_id`/`title`, non-http(s) url, char caps) | keep rows honest — required fields, http(s) URLs |

### The T2 sandbox

| Symptom | Cause | Fix |
|---|---|---|
| Instance shows `self-disabled: watchdog` | a call exceeded the wall-clock watchdog — kill = crash = self-disable (ADR-0030 clause 1) | fix the slow code or raise `CAREER_EXTENSION_SANDBOX_CALL_TIMEOUT_SECONDS`; then explicitly re-enable (the only way back) |
| Instance `self-disabled: crash` | the child exited hard (`os._exit`, native crash); host and other extensions unaffected | fix the extension; re-enable explicitly |
| `path-denied` from sandboxed code | the audit wall denied an fs-shaped attempt — there is no fs capability at this seam | keep data in `cap.state.*`, not files |
| `net-denied` on a declared-domain fetch | a hop (often a redirect) left the declared `domains` | declare every host in the chain |
| `budget` errors, run ends cleanly | a quota: concurrent sandboxes (>2), calls/min (>120), calls/run (>600), bytes/day (>64 MiB), state bytes | reduce work per tick; quotas are Settings (see the [knobs table](reference.md#sandbox-knobs)) |
| `protocol` errors, extension still alive | garbage lines on the seam — three strikes recycle the child, the extension survives | fix the RPC client usage (use the vendored `capability` module) |
| `unsupported` at handshake | protocol-version mismatch or the sandbox runtime is unavailable (frozen builds have no interpreter) | re-import content authored for the current protocol; on frozen builds T2 self-disables by design (`careerassistant enginecheck` probes) |
| Secret placeholder appeared in fetch headers instead of a value | `cap.secrets.need` returned unresolved status — values never cross the seam | fill the slot on the instance config; the host substitutes at fetch time |
| Orphaned runs closed `interrupted` at boot | a host restart is never extension failure (boot reconciliation) | nothing to fix — inspect `extension_sandbox_runs` for the history |

## FAQ

**Can I write a plugin that runs inside the app?** No — and that is
law, not missing features. In-process (T1) is reserved for code
reviewed and shipped with the product. Everything importable from
outside is T2 (sandboxed) or T3 (external process). The entry-point
group exists for deployment-image code and is admin-allowlisted.

**Why is my board connector denied by robots when the board's own API
docs welcome API consumers?** The runtime cannot read terms of service;
it reads robots.txt and fails closed. Where the terms genuinely welcome
API use, the operator can lift the verdict per deployment — that is
exactly why the escape hatch is admin-side.

**What exactly does the digest pin?** The content tree of the
extension's directory (regular files only, `.git` excluded), hashed
deterministically. Not the ref name, not the version string — the
bytes. That is why a tag force-move is detectable.

**Do updates need me again?** Yes, for code — always: an update is
offered and applied only by an explicit re-consent. Capability or
configSchema growth re-consents even on T0; only byte-identical-manifest
data diffs could auto-apply.

**Where do I see what a script actually did?** The AI audit funnel:
one `mcp_tool_call` row per tool call (T3), one
`sandbox_capability_call` row per capability call (T2), one `tool_run`
row per chat-tool execution — plus `extension_sandbox_runs` per spawn.

**Why did my instance vanish from the mini-app routes after I disabled
it?** The kill switch is a data boundary: only enabled installs surface;
a disabled install's route 404s.

**Is the sandbox a security review?** No. "Sandboxed, not reviewed" —
the sandbox limits blast radius; it is not a review of intent. The
residuals (Windows memory cap, `os.stat` metadata probing) are disclosed
in [Security & Gotchas](security-and-gotchas.md#the-sandbox-residuals-disclosed-not-mitigated).

**Can the assistant install or enable an extension for me?** No —
model output may never register, enable or schedule sources
(ADR-0011 §7); registration and the desired-state document are admin
acts by law.
