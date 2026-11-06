# Versioning & Migration

How the SDK versions, what may change, and what concretely happens to
installed extensions when it does.

## The envelope and per-kind versions

Three versioning layers, all validated at the seams:

- **`extension/v1`** — the envelope `apiVersion`, versioned as a string.
  A host accepts what it knows; a manifest carrying an envelope the
  host doesn't know is rejected at discovery/registration typed
  `unsupported` (fail closed, never best-effort parsed).
- **`kindVersion`** — the per-kind refinement (connector: `1` today).
  A host with a lower refinement than the manifest requires self-disables
  the import typed `unsupported` — "requires host connector refinement
  >= N (host has M)". Bumping the refinement is a breaking change by
  definition: older hosts refuse the new manifest.
- **`version`** — the extension's own semver, free to move; it feeds
  the update engine's manifest diff but never gates anything by itself
  (the digest is the pin, not the version string).

The `mini-app` kind keeps the separate ADR-0029 lineage — an integer
`apiVersion: 1`, no `kindVersion` — because its "envelope" is one
integer. Do not unify the two forms; hosts check them distinctly.

## Append-only vocabularies

Once shipped, these may gain values but never rename or drop one — the
charter's compatibility law, enforced by the fixtures:

- the 15 error codes (and the `retryable` set);
- the capability names (`sync`, `net`, `state`, `secrets`, `ui:*`, …);
- the RPC method vocabulary (`cap.*`, `ext.*`, `evt.*`);
- the status vocabularies (source status, install states, update
  states, run outcomes);
- the risk classes (`read-only | state-changing | destructive`);
- manifest field names and the `x-secret` convention.

A host that stops honoring a capability keeps accepting the manifest
(reported as a profile rejection with reason); a vocabulary entry that
vanishes is a bug.

## The no-shims doctrine

There are no compatibility shims: a breaking change re-authors
extensions, it does not convert them. Concretely:

- the host never rewrites an old manifest into a new shape at import;
- the sandbox protocol does not translate between `capability-rpc`
  versions — a handshake mismatch self-disables the install typed
  `unsupported`, never half-runs;
- bundled connectors are re-authored in the same commit as the SDK
  change (the conformance kit forces it: every connector must pass the
  current kit).

## What happens to an installed extension on a major bump

| Situation | What happens |
|---|---|
| Host upgrades past the manifest's `kindVersion` (manifest too new for the host) — reverse case: host too old | the install self-disables typed `unsupported` with the surfaced reason on the instance; nothing is removed |
| Extension ships `kindVersion: 2`, host has `1` | import/update rejected `unsupported` at the host-profile check — never installed |
| Envelope `extension/v2` appears | hosts on v1 reject at discovery; adoption is a coordinated family change (dev canonical first, schema + fixtures + hosts in lockstep) |
| A capability is retired from the host profile | the host-profile check fails on the next sync of the source; existing installs keep running their pinned digest until they update — the update requires re-consent and will be rejected if it still declares the retired capability |
| The T2 RPC protocol major-bumps | sandbox handshake fails ⇒ the install self-disables typed `unsupported`; the surfaced remedy points at re-importing content authored for the new protocol |

The invariant across all rows: **an installed extension keeps its
pinned digest running until an explicit, consented change** — hosts
degrade loudly (typed reasons on the instance), never silently mutate
or remove content. Data (content, consent records, pin history)
survives every one of these paths.

## Migration notes for authors

- Bump `version` freely; bump `kindVersion` only for breaking manifest
  shape, and expect older hosts to refuse.
- Add capabilities cautiously: growth on update **re-consents**
  (`requiresReconsent: true` with the diff recorded) — your users see
  exactly what was added.
- Changing `configSchema` also re-consents; changing only row-mapping
  code does not (digest change ⇒ update offered, still explicit).
- Renaming your extension `id` is a new extension (content dirs,
  instance keys and consent records key on it) — ship both for a
  transition window and let admins tombstone the old one.
