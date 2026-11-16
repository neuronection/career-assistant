# CV Studio overview

CV Studio is Career Assistant's most mature surface: a complete CV workspace
where every AI action is grounded in your structured profile. Open it at
`/cv`.

> Career Assistant is more than a CV builder, but if you are here for the CV,
> you are in the right place.

## Three ways to a CV

1. **From templates.** Start with a template from the versioned bank and edit
   it in the builder. See
   [Templates and design](cv-design-and-templates.md).
2. **From an existing CV.** Upload your CV (PDF, text or photo). The original
   is preserved byte-for-byte and an OCR text layer is added; the AI intake
   pipeline turns it into a **review-first draft** you confirm item by item
   (see [Onboarding and your profile](onboarding-and-profile.md#import-an-existing-cv)).
3. **On-demand AI generation.** Generate a whole CV from your profile in one
   shot: pick context sources and preferences in a modal, and a LangGraph
   draft flow plans and writes the CV with per-section fallbacks. It lands in
   the builder with an automatic restorable version.

### The polish loop

On-demand generation includes a **polish loop** that critiques the *rendered*
pages — vision review plus ATS lint plus a deterministic coverage matrix — and
applies fixes through the same audited path as the copilot. You choose how
many rounds to run (1–12). If a style brief keeps failing, the loop can
**escalate it to the AI template designer**. An **enrich step** fetches a few
of your own linked pages (GitHub repos, portfolios) on demand to ground the
descriptions.

## The builder workspace

The builder (`/cv/:id`) is a full-bleed workspace with a toolbar, a context
pane, the live canvas and an inspector. The inspector has three tabs, ordered
**Sections → Context → Design** (cover letters default to Context, where the
brief lives). One-off AI actions live in the toolbar next to **Ask AI**, and
read-only reports open from their toolbar chips — they are not tabs.

The **copilot** operates the builder for you (see
[Chat and proposals](assistant-chat.md#the-builder-copilot)).

## Per-CV context selection

The **Context** tab controls which profile items can render on this CV. The
renderer snapshot carries per-item traceability, and AI writing (summaries,
bullet rewrites, tailor-to-posting with must-have coverage, translate-assist)
**only sees what you included**.

Precedence is always:

**override > variant > source**

- **Bullets are strictly two-layer:** per-item bullets variants replace an
  item's achievement list; overrides never carry achievements. See
  [Variant library](cv-variants.md).
- **Check bullets** in the bullets editor runs a deterministic coach (no
  AI): it flags a missing number, a duty-phrase opening ("responsible
  for…"), passive voice, an over-long or very short line, and two bullets
  that start with the same opening word. Findings render under each line; you
  edit and save. The **Generate** action is separate and still produces
  review-only chips.

## Listing at a glance

Every CV card in the studio carries a **first-page thumbnail** printed by the
same engine as the PDF (downscaled and cached per edit), and the whole card
opens the CV. The list shows exactly your CVs — imported source files live in
the import workspace, not here.

## Honesty tools

- **ATS lint** with a one-click score report, opened from the toolbar's ATS
  score chip.
- **Parser view** ("What a parser sees", beside the ATS chip) — prints your
  current CV through the same engine as the PDF export and shows, verbatim,
  **what our own extractor reads back**: each printed page's text with its
  line count, plus deterministic findings — a missing text layer
  (image-only export), contact details that did not survive extraction,
  welded (joined) lines, a section order that deviates from the reading
  order, pages over budget and empty pages. It is read-only, creates no
  version and runs no AI; the panel says explicitly that this is **our
  extractor reading our printed PDF — not a simulation of any ATS
  product**. There is no score on this surface. Without the optional print
  engine the read answers 503 and the panel shows the same "not installed"
  message as the PDF export.
- **Page-count meter** with over-budget warnings. The **printed PDF is the
  page-count truth** (measured by a real print engine), not an estimate.
- **Versions** with text diff, image diff and restore.
- **Exports** to PDF, DOCX, Markdown, JSON and ATS text.

Drafts announce "review before exporting" — the app never pretends an
unfinished CV is ready.

## Tailoring from a posting: the kit

The tailor action ("Tailor to posting" with its must-have coverage) also
has a posting-side entry point: the [application kit](application-kit.md)
(`Tailor & apply` on a posting) shows the same evidence-first requirement
report and runs the **deterministic** comparison — missing sections and
covered/missing levels as review cards that open the right CV here. The
kit never writes into your CV and never drafts with AI; the writing
proposals stay in the builder, where every one is a draft you approve.

## Related

- [Application kit](application-kit.md)
- [Templates and design](cv-design-and-templates.md)
- [Variant library](cv-variants.md)
- [Cover letters](cover-letters.md)
- [Feature catalog](features.md#cv-studio) — the exhaustive list
