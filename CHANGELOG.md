# Changelog

All notable changes to **Career Assistant** are documented here.

## [Unreleased]

## [v0.7.1] - 2026-09-10

### Changed
- **Sidebar reconciliation** — the shell drops from 14 to 11
  items around one rule: surfaces that write the profile nest under
  Profile, activities stay top-level.
  - **Assessment** is now a profile workspace at `/profile/assessment`
    (rail entry + summary card on the profile page); `/assessment`
    redirects.
  - **Universities** become a fourth Catalog subtab
    (`/catalog/universities`, gated on the universities feature flag as
    before); list and detail routes moved, old URLs redirect.
  - **Live + Explore merge into one Postings surface**
    (`/postings`) with Feed | Search subtabs; `/explore` redirects to
    `/postings/search`. All feeds, filters, facets and saved searches
    keep working unchanged.
- **"Generate jobs with AI" is now a subtab of the Job Catalog**
  (`/catalog/generate`) instead of a standalone page — browse, then
  invent, in one place. The catalog tabs (Tree | Graph | Generate) are
  real URLs, so views are deep-linkable; `/generate` redirects to the
  new location (sidebar and Dashboard quick links updated).
  `/catalog?family=<key>` deep links now open the catalog pre-filtered to
  that family (previously silently ignored).

### Fixed
- Red `ruff format --check` CI gate — a missing trailing comma in
  `backend/app/ai/chat_models.py` failed the lint job.
- Stray "everyone" text rendered after the review-queue heading on the
  job-generation page; hardcoded "Review details" / "Publish all" labels
  are localized now.

---

Release history lives in [GitHub Releases](https://github.com/neuronection/career-assistant/releases)
(the pre-launch changelog was retired when the repository was republished;
tagged releases `v0.2.0` onward are listed there).
