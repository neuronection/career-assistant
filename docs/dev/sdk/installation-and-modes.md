# Installation & Modes (internals)

How connectors and extensions arrive on a Career Assistant instance —
the operator-facing half lives in
[Import extensions from git](../../user/import-extensions-from-git.md);
this page is the dev-side detail: bundled vs imported, the source
pipeline, artifact layout, and dual-mode notes.

## Bundled vs imported

| | Bundled (T1/T0 engines) | Imported (git source) |
|---|---|---|
| Arrives | shipped inside the app image | `source add` → sync → consent-install |
| Code runs | in-process, reviewed with the product | never in-process: T2 sandbox subprocess or T3 external MCP process |
| Registration | auto-register at import; manifest validated at registration | manifest validated at discovery + host-profile check; tier derived from `entry`/`mcp` |
| Enablement | a `job_sources` row with the connector key | install mints a **disabled** instance; enabling is an explicit act |
| Updates | app releases | digest-pinned; updates offered, applied only by explicit re-consent |
| Examples | `arbeitnow`, `remotive`, `jobicy`, `ats_api`, `jsonld`, `rss`, `csv`, `manual_url`, `mcp` (allowlist-gated) | `example-posting-fetcher` (T3), `t2-reference-scorer` (T2), `career-cv-gallery` (T0) |

The entry-point group `career_assistant.connectors`
(`backend/app/extensions/registry.py`) is **admin-opt-in via
`CAREER_CONNECTOR_PLUGINS_ALLOWLIST` and T1-bundled-only**: entry-point
plugins are code shipped in the deployment image. External authors write
T3 MCP connectors or T2 sandboxed connectors — there is no in-process
path from outside. The `mcp` builtin (the T3 bridge) is itself
allowlist-gated: without `mcp` in the allowlist it is invisible in the
catalog and unknown to the registry, and a T3 import fails `not-ready`
at mint time.

## The import pipeline

One pipeline, two modes — **manual** (admin adds a source in
Settings → Tools → Connectors, or via the CLI) and **GitOps** (an
admin-owned desired-state document reconciled at boot, hourly, and on
demand — see the
[GitOps recipe](examples-and-use-cases.md#recipe-5--a-gitops-admin-fleet)).

```
resolve → shallow fetch → discover manifests (subpath + one level)
→ schema-validate against the vendored envelope → host-profile compat
→ per-extension consent → pinned install
```

- **Descriptors** validate against the vendored
  `extension-sources.schema.json`: production descriptors are **https
  git URLs only** (ssh/`file://`/userinfo structurally inexpressible).
  The dev/test **`local`** variant serves sibling checkouts and
  dogfooding: absolute paths, no `..` at the seam, **gated off in
  production boots** (`path-denied` when `CAREER_APP_ENV=production`)
  and **confined to `CAREER_EXTENSION_LOCAL_SOURCE_ROOTS`** (the repo
  root must resolve under an allowlisted parent).
- **Ref strategies**: `release-tag` (resolves the latest release; takes
  no value), `tag-pattern` (highest semver wins, name-descending
  fallback), `branch`, `commit-pin` (40- or 64-hex). On the CLI:
  `--ref release-tag | --ref tag-pattern=v* | --ref branch=main |
  --ref commit-pin=<sha>`. The resolved identity is
  recorded as the pin ref.
- **Host profile (career)**: `connector` imports must be
  `extension/v1` with `kindVersion ≤ 1` and capabilities ⊆ `{sync,
  secrets}` for T3 (an imported script's own sockets are
  consent-disclosed, never granted as `net`) or ⊆ `{sync, net, state,
  secrets}` for T2; `mini-app` imports need `apiVersion == 1`, T0 tier,
  at least one honored `ui:*` capability, and **no** runnable entry.
- **Content caps**: manifest ≤ 512 KiB; trees ≤ 4096 files / 128 MiB —
  typed `invalid` beyond.
- **The install mints a disabled instance** (see
  [Core Concepts](core-concepts.md#instance)); enabling is the explicit
  `set_install_enabled` act (`POST /api/v1/admin/extensions/installs/{id}/enabled`).

Updates: an install records ref + digest. Identical digest at a moved
ref ⇒ the pin moves. Changed digest ⇒ the update is *offered*
(`state: available`, `requiresReconsent`) and applied only through the
explicit re-consent call (`source pin` CLI / the apply API) — there is
no auto-apply path at all (no signing service exists); T0 data diffs
would auto-apply only on a byte-identical manifest (capabilities +
configSchema unchanged). **Digest drift on a pinned ref** ⇒ loud
failure: install flags `digest-drift`, the source degrades, pins stay
untouched.

### Runtime prerequisites

The pipeline shells out to the **git CLI** (`GitTransport`), so the
*serving* process needs `git` on `PATH` — not just the build. The shipped
`docker/Dockerfile` installs it in the runtime stage (the dependency layer
purges its transient copy after `uv sync`, which is why an older image can
look healthy but fail every source), and CI asserts `git --version` in the
built image. A host without it answers the typed `not-ready` ("git is not
installed in this deployment") rather than crashing; rebuild/upgrade the
image. The settings surface asks
`GET /api/v1/admin/extensions/capabilities` (`git`/`local`/`zip`) and
gates the zip and local-path kinds on what this deployment allows — a
production boot hides those controls instead of letting them answer
`path-denied`. The git kind is always offered; a host without the CLI
shows the explicit warning instead.

### The operator feeder

A host may also accept **feeder** imports — a folder mounted into the
container, or an uploaded bundle zip — when the operator explicitly enables
them. This is a staging mechanism, never a live source:

- **Policy, default off:** `CAREER_EXTENSION_ALLOW_FEEDER_IMPORTS=1` plus an
  allowlist of container paths in `CAREER_EXTENSION_MOUNTED_ROOTS` (JSON list,
  e.g. `["/integrations"]`). The values must ride the compose
  `environment:` map — a `docker/.env` line alone never reaches the app (the
  compose files pass an explicit key map, and `extra="ignore"` would swallow
  it silently). A non-JSON roots value (e.g. `/integrations`) is a boot
  crash-loop, not a default.
- **Staged, not read:** the host copies the whole folder into
  `<data_dir>/extension-imports/mounted/<key>/<treeDigest>/` (regular files
  only; symlinks and special files refused, hardlinks copied so the alias is
  severed, tree caps, `.git`/`.venv`/`__pycache__`/`node_modules` stripped, a
  post-copy stability re-walk that fails typed if the folder changed
  mid-copy), initializes the synthetic one-commit repository inside a temp
  dir, then renames into the content address. Installs copy from there into
  `data_dir/extensions/<id>/<digest>/` — the mount is never executed or read
  by an installed instance.
- **Identity:** one source row per `(resolved folder, subpath)`, matched by
  the stable `mount_key` and displayed as the operator's `mount_path`. A
  second import refreshes in place; **Check** re-stages the folder, so a
  changed tree is a new digest *offered* as an update, applied only by an
  explicit re-consent.
- **No distribution channel:** feeder sources are `managedBy: manual`, are
  rejected by the desired-state document, and their host-local provenance
  never reaches a non-admin surface. An install from a feeder is still
  `originClass: imported`, minted disabled, consent-recorded and tiered.
- **Interpreter:** feeder-staged bundles run on the host's `sys.executable`
  (a `.venv` is never staged, so it cannot be executed outside the digest).
  Heavy dependencies need a custom image or vendored pure-Python packages.
- **T3 tier:** an MCP bundle also needs the script tier allowlisted
  (`CAREER_CONNECTOR_PLUGINS_ALLOWLIST`, likewise through the compose
  `environment:` map) — without it the install mints disabled and the enable
  step answers `not-ready: the mcp connector is not allowlisted`.
- **Contract:** the vendored schema bytes are unchanged; the
  `localSourceDescriptor` comment that says hosts must gate the local kind
  off in production is **superseded for opted-in hosts** by the operator feeder (the
  next scheduled re-vendor corrects the text). The exemption is call-site
  scoped to the feeder writers — a hand-authored `local` descriptor never
  rides it.

## Where artifacts live

```
<settings.data_dir>/extensions/<extension-id>/<digest>/   # content-addressed install content
                                        manifest.json    # the validated manifest
                                        <entry file>     # whatever "entry" names (the template's T3 writes server.py)
```

- Installed content is **DATA**: never `importlib`'d, never on
  `sys.path` (the structure probe enforces both). The T3 spawn command
  references the content path; the T2 sandbox spawns `child.py` with
  `--content-dir` there.
- Consent records, pin history and update state live on the
  `extension_installs` row; source rows (`extension_sources`) carry the
  descriptor, candidates and status. Tombstoning retains rows, content
  and consent history — removal never deletes data.
- Frozen desktop builds: the vendored contract set ships as data at
  `sys._MEIPASS/contracts/`; the sandbox child assets ship beside it.
  A frozen build has no real interpreter behind `sys.executable`, so
  **T2 installs honestly self-disable** there (typed
  `SandboxRuntimeUnavailable` → `unsupported`) until the host runs from
  source or a runtime interpreter is dropped at
  `<bundle>/runtime/python`. T3 stdio spawns ride
  `get_default_environment()` through fastmcp, so spawned scripts do
  resolve their interpreters inside PyInstaller bundles.

### The managed spawn's interpreter

A managed T3 stdio install mints a source whose command runs the
content dir's `server.py` — but the *interpreter* is chosen at mint
time (`lifecycle._bundle_interpreter`):

- **local sources** — the bundle checkout's own
  `.venv/bin/python` when it exists (one `uv sync` in the checkout
  gives the bundle its dependencies), re-minted identically on
  re-import; **feeder-staged sources never use a `.venv`** (it is stripped
  during staging, so it cannot sit outside the digest) and run the host
  interpreter;
- otherwise — the host's `sys.executable` (frozen desktop builds ship
  their own interpreter, so this is the working default there).

A bundle whose fetcher needs dependencies the host does not carry (a
browser engine, heavy parsers) therefore works from a local checkout
without any host change. Two hard rules keep the digest fence intact:
never run `uv sync` inside the **managed content dir** (the install's
digest covers that tree — drift refuses to spawn), and never swap the
managed entry file — edit the checkout and re-import instead.

## Dual-mode notes (web vs desktop)

Both product modes share the whole subsystem — one pipeline, one schema
(dialect-aware). Differences worth knowing:

| | Web/self-host (Postgres) | Desktop (SQLite) |
|---|---|---|
| Sources | full surface; production boots accept **https git sources** — plus the **operator feeder** (zip upload / mounted folder) when the operator enables `CAREER_EXTENSION_ALLOW_FEEDER_IMPORTS` | local sources allowed when run in development with allowlisted roots |
| Scheduler | reconcile at boot + hourly (`system_extension_reconcile`) | same engine, background scheduler in the tray app |
| Sandboxed T2 | works from source installs | works in dev; frozen builds self-disable honestly (see above) |
| Admin seat | Settings → Tools → Connectors (auth: admin) | same surface, desktop's implicit local owner |

## The import layer's consent step

Every import renders the consent payload before anything lands —
capabilities, tier, provenance verbatim, digest, and the tier's
disclosure verbatim. The disclosures and what they mean are covered in
[Security & Gotchas](security-and-gotchas.md) and, in plain language,
[Consent, explained](../../user/extension-consent.md).
