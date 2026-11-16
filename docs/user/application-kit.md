# The application kit

The kit turns a saved posting into a reviewable application: one page
with the requirement report, your CV variant, the cover letter, common
screening answers to prepare and a pre-flight checklist — and, once you
say so, the tracker timeline. It is the "one great application" surface:
everything is evidence-backed and nothing applies for you.

## Before you apply: the posting kit

Open a posting and choose **Tailor & apply** — or go straight to
`/postings/:ref/kit`. The pre-application kit shows:

- **CV variant** — the posting-tailored CV when you have one (marked
  *For this posting*), your other CVs, and the evidence-first
  requirement report (the same one from the posting page). **Prepare**
  runs the deterministic comparison again: sections your CV is missing
  (as review cards — *Open in CV Studio* to act, *Dismiss* to hide) and
  the covered/missing split. No AI runs here; writing proposals stay in
  CV Studio's own draft-then-approve actions.
- **Cover letter** — the letter targeted at this posting when one
  exists, or an explicit **Create cover letter** button. Creating it
  opens an empty letter workspace for this posting; draft and approve
  the paragraphs in CV Studio (every paragraph cites profile evidence).
- **Answers** — common screening prompts (availability, work
  authorization, salary expectations and the languages the posting
  mentions) backed by your own saved answers. Write or edit the text and
  press **Save**; the next posting reuses it. **Clear** deletes the saved
  answer. Nothing is generated and nothing is auto-filled into an
  application form.
- **Checklist** — read-only and sourced: whether the posting is still
  open (from the source's expiry date), the **measured** page count of
  your CV (from the same lint and PDF engine CV Studio uses — never an
  estimate), header contact findings from the lint, and a few static
  file hints (send PDF, keep it small, name it well). It is general
  guidance, not a simulation of any ATS product.
- **Timeline** — empty until you track the application.

If you have no CV at all, the kit says so and links to CV Studio. If
the posting has no deep extraction yet, the requirement report says so
too — degraded but explicit, never guessed.

## Mark as applied

When you are ready, choose **Mark as applied**. That records the
application in the tracker with the documents you pick (your variant CV
and the posting's letter are preselected) and opens the application kit
at `/applications/:id`. Career Assistant submits nothing anywhere: you
apply on the original site (the kit keeps the **Open original** link
handy), the tracker only records that you did.

## After: the application kit

Every application now has a full kit page at `/applications/:id` — the
same five tabs with the event timeline and the linked documents on the
Timeline tab. Reach it from the tracker's **Kit** button on any card,
row or drawer, or from the posting page once an application exists.
Document changes still go through the tracker's audited actions
("Link to application" on the CV and letter tabs does exactly what the
drawer's document form does, and the drawer remains the place for
stages, notes, follow-ups and closing).
