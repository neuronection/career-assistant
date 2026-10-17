# Import extensions from git

Beyond the bundled engines, Career Assistant can import connectors and
mini-apps from **git sources** — any repository that carries extension
manifests. Every import is digest-pinned and consent-gated: you see
exactly what you're installing, and updates never apply on their own.
The surface lives at **Settings → Tools → Connectors → Import
connectors from git sources** (admin).

## Add a source

A source is a git repository plus which ref to track. In production the
address must be an **https git URL**; private repositories work with a
credential slot (a sealed token — never stored in the URL). Developer
setups can also use a local checkout, confined to allowlisted folders
and rejected outright on production instances.

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
