# Import extensions

Beyond the bundled engines, Career Assistant can import connectors and
mini-apps three ways: from **git sources** (any repository that carries
extension manifests), from an uploaded **bundle zip**, or from a **folder
mounted into the container** (self-hosted, operator-enabled). Every import
is digest-pinned and consent-gated: you see exactly what you're installing,
and updates never apply on their own. The surface lives at **Settings →
Tools → Connectors → Extension sources** (admin).

A source is one **origin + subpath** pair: a multi-bundle repository
(several `*/src/` bundles in one repo) registers one source per bundle
subpath, and each source discovers and offers only the manifests under
its own subpath.

## Import a bundle (.zip)

Handy when the bundle lives on your machine instead of a remote: the
**Import bundle (.zip)** button takes a zip of the bundle (its
`manifest.json` at the root or one level down), stages it locally as a
pinned source, and runs the exact same flow — validate, consent,
digest-pinned install. The zip is never executed directly, and "update"
means uploading a new zip and consenting again (updates never apply on
their own). Zip import is **off by default in production**: a self-hosting
operator can enable the feeder policy (`CAREER_EXTENSION_ALLOW_FEEDER_IMPORTS`)
on the `app` service, after which the button appears and the same flow runs
on the server. Without it, production stays git-only and the control is not
offered. In the desktop shell, when the instance allows zip import, the file
dialog is the native picker.

## Import from a mounted folder (self-hosted)

When the operator has enabled the feeder policy, a folder mounted into the
container is importable as a source: the host copies it into its own store,
pins the snapshot and runs the same consent flow. Mount it read-only and
allowlist the container path, for example:

```yaml
services:
  app:
    volumes:
      - ./integrations:/integrations:ro
    environment:
      CAREER_EXTENSION_ALLOW_FEEDER_IMPORTS: "1"
      CAREER_EXTENSION_MOUNTED_ROOTS: '["/integrations"]'
```

Then **Install from Git** → *Mounted folder*, enter the folder path inside the
container (for example `integrations/my-tool`) and confirm. **Check**
re-stages the folder: a changed tree is offered as an update and applies only
after a second consent. A mounted source is never managed by GitOps, and its
folder is not part of the backup — re-attach it before pressing Check after a
restore.

## Add a source

A git source is a repository plus which ref to track. In production the
address must be an **https git URL**; private repositories work with a
credential slot (a sealed token — never stored in the URL). Developer
setups can also use a local checkout, confined to allowlisted folders
and rejected outright on production instances. A **mounted folder** takes
no ref at all — the host pins the snapshot it stages.

Adding a source fetches it once and lists every extension it offers
with its compatibility — an incompatible extension says so with a
reason; nothing is installed yet.

## Consent, then install

Pick an offered extension and choose **Install with consent…**. The
consent dialog shows, in full:

- what it is — id, version, author, license, repository, description;
- the **capabilities** it asks for (e.g. network fetches scoped to
  named domains, stored state, secret slots);
- the **trust tier** it installs as — sandboxed code, an external
  script process, or declarative data;
- the exact **content digest** — the sha256 of the bytes you're
  accepting (the app pins the install to it);
- the tier's plain-language disclosure of what that tier means.

What those disclosures mean is covered in
[Consent, explained](extension-consent.md). Confirming (**I consent —
install**) downloads nothing new — it pins the content already fetched
and creates the instance **disabled**.

## Enable and use

Imports never enable themselves. Turn the import on in
**Settings → Tools → Connectors → Extension sources (git import)**,
then sync it like any source. A connector starts feeding postings; a
mini-app appears in the sidebar's Extensions section with its own page.
Disabling it again hides it completely — that's the kill switch.

## Updates: offered, never applied

Sync a source (or let the hourly reconcile do it for fleet-managed
ones) and the app checks for new versions. When an extension you
installed publishes an update, the instance shows it with a summary of
what changed (version, added capabilities, config changes). Applying it
is always a second, explicit consent —
**Apply update (re-consent)**. There is no auto-update path for
imported code, on purpose: a version jump that asks for new
capabilities gets the same consent review as the first install.

If the repository's history is rewritten so the *same* release
suddenly contains different bytes, the app refuses loudly
(*digest drift*) and waits for you to verify and re-consent — that
signal exists to catch tampered sources.

## Removing

Removing a source (or tombstoning an instance) disables the extension
and keeps everything else: the downloaded content, your consent
history, the audit trail. Re-importing at the same content brings the
history back — nothing silently re-enables.

## Related

- [Consent, explained](extension-consent.md) — the three tiers and
  their disclosures
- [Add a job source](add-a-job-source.md) — the bundled boards need
  none of this
- [Extension troubleshooting](extension-troubleshooting.md)
