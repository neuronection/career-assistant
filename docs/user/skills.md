# Skill pages

Every skill in the taxonomy has its own page at `/skills/:key` — one
place that aggregates what the app knows about a skill: what it is, who
demands it, how it relates to other skills, and how it has changed. Open
it from the skills table in **Settings → Taxonomy** (the **Details**
preview, then **Open skill page**), from a node's right-click menu in
the relations graph, from the related-skills chips on any other skill
page, or from the footer of the skill peek — the compact popup that
opens when you click a skill chip on any posting card or on the posting
detail page (a chip the taxonomy doesn't know yet shows a
pending-review note instead).

The page is organized in four tabs.

## Overview

The always-visible header shows the skill's label, its stable key, its
lifecycle state (proposed / active / deprecated), its category, aliases
and its place in the tree (a link to the parent skill). Skills that were
merged away keep their page with a banner pointing at the surviving
skill.

Below the header:

- **Stat tiles** — how many live postings demand the skill, the average
  required level (1–10), how many people have the skill on their
  profile, and when postings last asked for it (first/last seen).
- **Level distribution** — the histogram of required levels across
  postings.
- **What the levels mean** — the skill's level anchors, so "level 7" has
  a stated meaning.
- **Your skill** — your own level for this skill (or "not in your
  profile"), the demand average for comparison, and an Add/Update
  control. Self-reporting an unknown key creates a `proposed` skill, so
  your profile is never blocked by a missing vocabulary entry.
- **Catalog jobs** — the curated catalog jobs that ask for this skill,
  with their required level and importance.
- **Related skills** — chips for the skill's approved neighbors; each
  opens that skill's page.

## Positions

The postings whose deep extraction found this skill, newest first — the
same cards as the postings feed, including the closed-state chip for
expired postings (hidden postings never list). Use **Load more** to page
and **Open in Explore** to carry the skill filter into the full search
(`/postings?skills=key`, where `key:level` can also ask for a
minimum required level).

## Graph

The skill's approved relations as a depth-1 diagram — the skill, its
direct neighbors and the typed edges between them (is a / synonym /
part of / related to). Click a node to jump to that skill's page. Admins
get a link to the full graph in the taxonomy admin.

## History

The skill's lifecycle journal, newest first: created, updated, promoted,
auto-promoted (when two distinct postings corroborated an extracted
label — see [the taxonomy admin](skills-taxonomy.md) for the review
side), deprecated, restored, merged and deleted events, each with a
timestamp, the acting role (admin / system / sync / job / you) and a
compact summary of what changed. The journal survives deletion: a
deleted skill's page is gone, but nothing rewrites the audit trail.

## Admin actions

Admins see the lifecycle actions in the header — promote a proposal,
deprecate, restore, merge into an active skill, edit (label, category,
description) and delete an unreferenced skill. Every action lands back
on the page with the new event visible in the History tab: the page is
its own audit view.
