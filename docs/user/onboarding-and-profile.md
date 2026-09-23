# Onboarding and your profile

Your profile is the structured foundation for everything else: matching,
rankings, postings, Autopilot and CV generation all read it. Because it is
typed and validated (not free text), the app can compute matches and
generate CVs from it deterministically.

## The onboarding wizard

The wizard walks you through the sections that matter, one card at a time:
interests, skills, work-style preferences, education and constraints.

**Start paths.** Before the sections, pick why you are here — the wizard
then asks only what your path needs:

| Start path | What it asks for |
|---|---|
| **Explore careers** | Interests and work-style preferences; enough to start browsing |
| **Target a known job** | The role you want plus two questions; live postings, alerts and suggestions start immediately (target mode) |
| **Start from your CV** | Upload an existing CV; the intake pipeline pre-fills a reviewable draft |
| **Just browse** | The minimum; you can fill the rest later |

You can leave and return to the wizard at any time; progress is saved
per section. **Express start** (`/onboarding/express`) is the shortcut for
people who already know their target.

## Profile sections

The profile page (`/profile`) is a two-pane layout: a sticky section rail
with a completeness dot per section on the left, the active section's card
on the right. Sections save themselves as you edit — there is no separate
"save the profile" step for section-level fields.

| Section | What it holds |
|---|---|
| **Basics** | Name, contact details, location, headline |
| **Objective** | A short statement of what you are aiming for |
| **Interests** | Taxonomy-referenced interest tags (stable `key` slugs, never free labels) |
| **Skills** | Open-vocabulary skills with a 1–10 level. Unknown skills you type become `proposed` rows, never lost |
| **Work style** | Preferences across work-style scales |
| **Work values** | What matters to you in a role (scored by the fit engine) |
| **Languages** | Spoken languages with levels and optional proficiency exams |
| **Constraints** | Location, salary minimum, remote/onsite, lifestyle gates |
| **Career stage** | Student, early career, experienced, switching or returning (derived when unset, always correctable) |

Two sections open dedicated **workspaces** instead of inline editing:

- **Experience** (`/profile/experience`) — a master-detail workspace over
  your jobs, internships, freelance work, projects and volunteering, with
  bulk select/activate/delete, duplicate, filtering and an undo window for
  deletes.
- **Education** (`/profile/education`) — the same pattern over education
  entries, certifications and achievements, with an entity toggle in the
  toolbar. Institution pickers search the university catalog and accept
  free text.

Both workspaces accept deep links from elsewhere in the app (for example
from CV Studio's context panel) that open the right entry with a highlight.

## Import an existing CV

You can start your profile from a CV you already have — from the onboarding
wizard, or any time via **Profile → Import from CV** (or
`/profile/import`).

1. Upload your CV as a **PDF, text file or photo**.
2. The intake pipeline reads it and produces a **reviewable draft** — nothing
   is written to your profile yet.
3. Review each section item by item: tick what to keep, check the confidence
   pill and the verbatim evidence quote behind each extracted value.
4. For contact details, where your profile already holds a different value,
   the row turns amber with "Now: …" and an explicit **Keep/Replace**
   control — existing data is never silently overwritten.
5. Apply. Applied items become active by default (your ticks are the
   approval); you can also save them as drafts.
6. A "Landed in your profile" row links to everything that was written, and
   the processed document stays browsable from the import history.

Your original file is preserved byte-for-byte; only a text layer is
extracted. See the [feature catalog](features.md#profile) for the full
pipeline.

## AI profile analysis

Ask for an external read on your profile and what it implies — strengths,
gaps and suggestions. The analysis is generated through the audited AI
pipeline and never changes your data on its own.

## Editing from chat

You can also change your profile from the assistant: ask it to update an
experience entry or add a skill, and it proposes the change as a **review
card** with a before/after preview and one-click revert. Changes are never
auto-applied. See [Chat and proposals](assistant-chat.md).

## Related

- [Assessment and metrics](assessment.md) — refine your skill levels and
  interests with the JobTypeMatch assessment
- [Matching and rankings](matching-and-rankings.md) — how your profile
  becomes a score
- [CV Studio overview](cv-studio.md) — turn the profile into a CV
