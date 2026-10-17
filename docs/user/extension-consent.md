# Consent, explained

Whenever Career Assistant imports an extension from outside — a
connector from a git source, a mini-app — it asks for your consent
first, and shows you the same things every time. This page explains
what that dialog means and why the app is built this way.

## What you are shown

1. **Provenance** — the id, version, author, license, repository and
   description exactly as the extension's manifest declares them. This
   is who claims responsibility for what you're about to run.
2. **Capabilities** — what the extension asks to do: run on the sync
   schedule, fetch from named internet domains, keep stored state, use
   secret slots. The app enforces this list; asking for less than you
   use simply fails later.
3. **The trust tier** — where the extension's code will actually run.
   There are exactly three possibilities for imports, each with a
   disclosure shown word-for-word from the family charter.
4. **The digest** — a sha256 fingerprint of the exact bytes being
   installed. The install is pinned to it. If those bytes ever change
   under the same release name, the app notices and refuses.

Your consent is recorded — who consented, when, and to which digest —
and kept even after you remove the extension.

## The three tiers, in plain language

**Declarative data (no code).**

> This extension is declarative data only: it carries no code, and the
> app renders exactly what it declares — validated against a closed UI
> vocabulary and schema at import. Content stays inside the app's
> rendering and theming; nothing from this extension executes or reaches
> the network on its own.

A mini-app like the CV theme gallery is just data the app draws with
its own components.

**Sandboxed code.**

> This extension's code runs sandboxed, not reviewed. Sandboxing limits
> the blast radius of this code; it is not a review of its intent. The
> import is pinned to this exact content digest.

Sandboxed code runs in a strictly confined subprocess: no files, no
arbitrary network, no reading the app's environment; every request it
makes goes through the app's politeness guard; quotas cap its time,
memory and traffic. The honest part of the sentence is "not reviewed":
the sandbox limits damage, it does not tell you the author's intent.
Your judgment + the pinned digest are the trust decision.

**External process.**

> This extension runs as a separate process outside the app's network
> perimeter. It opens its own network connections, with no SSRF guard,
> robots.txt check or rate limiting by the app. The app governs only
> what it returns: outputs are validated and capped.

A script connector is a separate program the app talks to. It can reach
the internet however its author wrote it — which is why the app
validates everything it returns and caps it, and why this tier is off
until an admin turns it on.

## Why updates ask again

Consent follows the browser-permission model. When an update changes
what you consented to — new capabilities, new config fields, or any
code change at all — the app offers the update and waits for an
explicit **Apply update (re-consent)**. Nothing self-applies. The one
signal louder than an update is *digest drift*: the same release now
containing different bytes. That's treated as a possible tampered
source: the app degrades the source, touches nothing you have
installed, and waits for a human.

## What never needs consent

The bundled engines — the job boards, RSS, CSV, ATS, the posting
extraction — ship inside the app, reviewed with it. Enabling them is an
ordinary settings toggle, not an import.

## Related

- [Import extensions from git](import-extensions-from-git.md) — the
  how-to this page explains
- [Chat tools, risk badges and approval](chat-tools-and-approval.md) —
  the same model for what the assistant's tools may do
- [Privacy and security](privacy-and-security.md) — where your data
  lives and how keys are encrypted
