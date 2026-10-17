# Core Concepts

The nouns this doc set leans on, defined once each. They come from the
family extension charter (ADR-0040) — the same words across every
Neuronection host.

## extension

A versioned, manifest-described unit the host can install and run. The
manifest is **data, never code**: it validates against the vendored
envelope schema (`extension-manifest.schema.json`) at registration or
import. An extension has exactly one `kind` (career hosts `connector` and
`mini-app` imports; every bundled posting engine is a `connector`).

## kind

What the extension *is*, refined per kind by a version: `connector`
(envelope `extension/v1`, integer `kindVersion`), `mini-app` (the
ADR-0029 integer `apiVersion: 1` lineage, no `kindVersion`). The kind
decides which host profile checks apply — a `connector` needs a runnable
entry; a `mini-app` must declare at least one `ui:*` surface capability
and must NOT carry one (its artifact is validated data).

## tier

Where the code runs — the trust ladder. **T0** declarative data (no
code), **T1** bundled in-process (reviewed, shipped in the image),
**T2** imported code behind the capability-RPC sandbox (one subprocess
per extension), **T3** an external MCP process the app calls. Tier is
**provenance at install**: the artifact shape decides — `extension.py`
beside the manifest ⇒ T2, `server.py` ⇒ T3, both or neither ⇒ rejected.
Imported third-party code never runs in-process.

## capability

What an extension may do, declared as a closed list on the manifest and
**enforced, not believed**: `sync` (run on the posting sync schedule),
`net` (network fetches through the host's polite runtime, scoped to the
manifest's declared `domains` on every hop — requires them), `state`
(extension-owned persisted state, quota'd), `secrets` (secret slots
resolved host-side), `ui:page`/`ui:panel`/`ui:window` (declarative
surfaces), `run`, `report`. The host honors a per-kind, per-tier subset
at import; an unhonored capability is a typed rejection, never a warning.
Separately, chat tools carry a **risk class**
(`read-only | state-changing | destructive`) — that vocabulary governs
the invocation funnel, not capabilities.

## instance

The running configuration of an extension: for connectors, a
`job_sources` row (its `connector_key` + validated config + sealed
secret slots). Bundled connectors mint instances directly; imports mint
theirs at install — a T3 install mints a disabled `mcp` job source whose
stdio command spawns the cloned `server.py`; a T2 install's instance key
IS the extension id, and the registry routes it through the sandbox
runner. Enabling an instance is an explicit admin act; a killed instance
is the kill switch (its surface routes 404).

## source

Where imports come from: a git repository described by a descriptor
(`https://` git URLs in production; the dev/test `local` file-path
variant, gated off in production boots and confined to allowlisted
roots). One source can offer several extensions (discovery scans the
configured subpath plus one level of child directories). A source row
carries status — `ok`, `degraded` (e.g. digest drift), `failing` (failed
fetches; pins untouched) — with `last_success_at` and
`consecutive_failures`.

## consent

The gate before any imported code or data lands. The consent surface
shows, per extension: capabilities, tier + import class, provenance
verbatim from the manifest (author/license/repository/description), the
pinned digest, and the tier's disclosure **verbatim** (charter copy,
never paraphrased — see [Security & Gotchas](security-and-gotchas.md)).
Consent records persist on the install (who/when/what-digest) and
survive tombstoning. Capability growth, configSchema changes, or any
code update **re-consent** — the browser-permission model; there is no
auto-apply path at all.

## digest

The sha256 over an extension's content tree (deterministic walk, regular
files only, adversarial caps). It is the pin: content lands
content-addressed under `data_dir/extensions/<id>/<digest>/`, the
install records digest + ref, and a digest that changes under the *same*
pinned ref is **digest drift** — a loud failure (source degraded, pins
untouched, never a silent refetch), because it is the supply-chain
attack signal.

## How they connect

```
                    family charter (kinds, tiers, capabilities, consent copy)
                                      │
   ┌──────────────────────────────────┼──────────────────────────────────┐
   │  bundled (T1)                    ▼              imported (T0/T2/T3) │
   │  builtin/*.py ──manifest()──► registry ◄── resolve_connector ── sync │
   │                                   │                                │
   │                     in-process    │      source ─► discovery ─► consent
   │                                   │        (git/local)  │           │
   │                                   │                      ▼           │
   │                                   │            install pinned-by-digest
   │                                   │                      │           │
   │                                   │        ┌─────────────┴───────┐   │
   │                     T3: mcp job source        T2: instance key =   │
   │                         spawns server.py         extension id,      │
   │                         (own process)            sandboxed child    │
   │                                   │                                │
   │                                   ▼                                │
   │            instance (job_sources row: key + config + sealed secrets)│
   │                                   │                                │
   └───────────────────────────────────┼────────────────────────────────┘
                                       ▼
             sync: fetch(config, state, transport, secrets) →
             { items: RawPosting[], next_state, partial_errors } →
             postings, mapping, fit, feed, alerts
```

Everything network-shaped for T1/T2 funnels through the injected **polite
transport** (SSRF guard, robots fail-closed, per-host rate caps,
conditional GET) — connectors never open sockets themselves. The T3
process's own sockets are outside that perimeter by design and consent
disclosure; the host governs only what it returns (rows validated and
capped app-side).
