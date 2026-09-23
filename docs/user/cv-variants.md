# Variant library

The variant library (`/cv/synth`) lets any CV prefer an **item variant** over
the verbatim profile text — without editing your profile. Variants are
AI-written or manual, and they are reusable across CVs.

## What a variant is

A variant rewrites or reshapes one item from your profile:

| Kind | What it does |
|---|---|
| Summarized | A shorter version |
| Expanded | A richer version |
| Restyled | The same content in a different voice |
| Aimed at a posting | Tailored to a specific role |
| Translated | In another language |
| Custom instruction | Steered by your own instruction |
| **Bullets-only** | Replaces just the item's achievement list |

A variant cites its **typed source refs** and source content hashes, so the
app can detect when the underlying item changes.

## Staleness and orphans

When the source item changes, the variant is flagged **stale**. When the
source is deleted, it becomes an **orphan**. Neither is silently applied — the
badges tell you the variant no longer reflects its source.

## Starring and pins

- **Star to activate.** A star applies a variant to a CV.
- **One variant per item.** Pins are surgical: setting a pin on one item never
  disturbs another item's star.
- A variant can apply **per field** — text layer, bullets, or both — and a
  **scope badge** shows its provenance.
- **A pinned ref is exclusive:** if the star cannot apply (for example a draft
  or a different language), the item renders its profile text and **no other
  variant jumps in** — the star never lies silently. The UI marks it amber
  "not rendering".

Precedence on a CV is always **override > variant > source**. Bullets are
strictly two-layer: a bullets-only variant replaces the achievement list while
the description keeps rendering.

## The variant editor

The dedicated editor drafts fill-in-form with a **slot comparison** against
what is on the CV now, and an **in-editor AI generate-fill**. Manual variants
are first-class: language and posting scope are recorded at creation and are
not editable afterwards.

## Where to find it

- The **Synth Library** page (`/cv/synth`) manages the whole library.
- The builder's **Context** tab shows variants as a tree under their sources,
  with stale/orphan badges and status toggles.
- The main chat can also list variants and set or unset per-item pins on an
  attached CV (see [Chat and proposals](assistant-chat.md)).

## Related

- [CV Studio overview](cv-studio.md) — context selection and precedence
- [Templates and design](cv-design-and-templates.md) — change the look
- [Feature catalog](features.md#cv-studio) — the full variant surface
