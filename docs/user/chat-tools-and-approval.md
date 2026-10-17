# Chat tools, risk badges and approval

The assistant can act, not just answer: it searches your postings,
tunes your profile, and — where you allow it — runs tools that change
things. Every tool carries exactly one **risk class**, and the app
shows it as a badge and enforces it at invocation time. The same law
covers tools contributed by imported extensions.

## The three risk classes

| Badge | Meaning | What it takes to run |
|---|---|---|
| **Read-only** | Looks at data, changes nothing | Runs freely inside the chat |
| **State-changing** | Writes something — a saved search, a profile tweak, an export | Runs only after you enable that specific tool once |
| **Destructive** | Deletes or irreversibly changes data | Can never run directly from chat — it becomes an approval card |

You'll find the state-changing ones in the chat tools dialog under
**Needs your enablement**, each with a toggle. Until you flip it, a
call fails with a visible, typed message — the tool is inert by
default, never silently skipped.

## Approval cards (destructive tools)

When the assistant calls a destructive tool, the call does not execute.
Instead a **confirmation card** appears in the conversation with a
two-step confirm — the same surface profile edits use. Approving runs
that one call with those exact arguments, at most once; a crash midway
leaves an honest error on the card, never a half-applied retry loop.
Approving one deletion never authorizes deletions in general, and
enabling a grant never bypasses the card — the app simply refuses to
wire destructive tools to grants.

## Why trust the funnel, not the model

The risk class is declared in the tool's registration and enforced by
the one executor every tool call goes through — the model's request
cannot outrank it. Nothing in a model's reply can arm execution, and
feeding a card's result back as new tool arguments produces, at most,
another card. Every execution lands in the instance's AI audit log
(the same funnel that records AI generations and connector calls), so
"who ran what, when" is answerable after the fact.

## Extensions that contribute tools

Bundled connectors may contribute chat tools; their risk classes are
declared in the connector's manifest and cross-checked against the
implementation at startup — a mismatch is a startup error, not a
warning. Imported extensions' tools follow the same funnel: read-only
runs, state-changing needs your enablement, destructive always cards.

## Related

- [Consent, explained](extension-consent.md) — the import-side trust
  model
- [Chat and proposals](assistant-chat.md) — the conversation surface
  these cards ride on
- [Settings reference](settings.md) — where the tools dialog lives
