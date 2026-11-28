# Data providers

Admins manage the job-source **data providers** at
[Tools → Sources → Data providers](/settings/tools?section=sources). A
provider publishes versioned **packs** of presets (employer ATS tenants) and
public endpoint hints. Packs are data: the app fetches them, stores an
immutable content-addressed version, and nothing reaches the catalog until you
approve that exact digest and apply it.

## What ships with the app

**No catalog or reference-bank content.** The app bundles no presets and no
bank rows — a fresh instance's preset gallery, assessment, CV gallery, metric
surfaces and skill-pack list are empty until you add a pack, so there is one
source of truth for listings and no app release is needed to refresh them.
Each empty surface names what is missing and links here.

- **Official Neuronection provider** — four disabled Git tiles pinned to a
  released tag of the public
  [career-assistant-seeds](https://github.com/neuronection/career-assistant-seeds)
  repository: Greece ATS, worldwide remote boards, the curated job catalog,
  and the reference banks (assessment questions/batteries, CV layouts, metric
  dimensions and AI skill packs). **Sync now**, approve and apply a pack to populate the gallery or
  the catalog — or use the empty catalog page's **Load the official catalog**
  button, which installs the reference-banks tile first and the catalog after
  it. Skill packs apply as drafts; publish one from the provider hub to make
  it govern a task.

## Add your own provider

1. Open **Data providers** and choose **Add provider**.
2. Pick a source:
   - **Git repository** — a public HTTPS repository, a pinned tag or commit,
     and the pack subpath (`packs/<publisher>/<pack>`).
   - **Index URL** — a static `seed-repo.json` index (for example the official
     mirror at `https://neuronection.com/api/v1/career/`).
   - **Uploaded pack** — a pack zip containing `manifest.json` and
     `items/**.json`; it stays on your instance.
3. Give it a name, priority and trust tier. Higher priority wins when two
   providers publish the same seed key.
4. **Create**, then **Sync now** (uploaded packs already carry their content).
   Once a version is approved and applied, its presets appear in the source
   gallery enabled; switch individual items off in **Items** if you need to.

Open a provider to see what its applied version owns: the **Items** tab
lists posting presets, **Endpoints** lists endpoint hints, and **Catalog**
counts the job families, jobs, relations, career paths, skills and interests
it supplied. Catalog rows an admin edited directly are flagged as edited, and
a row a newer version dropped is shown as retired, never deleted.

One provider owns one pack. The official repository publishes four — Greece
ATS, worldwide remote boards, the job catalog and the reference banks — so it
arrives as four separate tiles, each disabled until you enable it. Any other pack in the same
repository is added as another Git provider with that pack's subpath.

To add a repository's packs in one step, choose **Repository (all packs)**,
enter its URL and pinned ref, and add: the app reads the repository's
`seed-repo.json` and creates one provider per pack (packs already present are
left alone). Nothing is fetched or applied — each provider still needs its own
sync, plan preview and approval.

## Review, approve and apply

The provider detail panel is a small workspace:

- **Overview** — source, ref/subpath, priority, refresh cadence, current and
  latest version, last check and the last sync error.
- **Versions** — each fetched pack is an immutable version with its digest and
  commit. **Preview plan** shows exactly what applying it would do:
  `create`, `update`, `noop`, `skip`, `retire` or `override` per seed key.
  Two providers at the same priority that disagree are a **conflict**: the
  whole apply is refused, so the catalog never half-changes.
  **Approve** a pending version, then **Apply** it. **Revoke** an approved
  version and the previous approved version is restored (or the catalog rows
  it introduced are retired).
- **Items** — switch individual presets on or off for the gallery, or retire
  one. Retiring marks referencing sources as unsupported; it never deletes a
  source you created.
- **Endpoints** — public endpoint descriptors, with an admin-only **Probe**
  that returns status, latency and content type only (no body).
- **Runs** — the fetch ledger: trigger, status, HTTP status, bytes, commit and
  any typed error.

Applying a version never creates or removes a job source by itself. Sources
you already created keep working; the provider only owns the catalog rows.
A provider's trust tier (`official`, `operator`, `community`, `local`) is shown
on every card; trust never bypasses approval.

## Follow and hide (every user)

The radar page carries the user-level view of the same catalog:

- **Follow** a provider to keep its sources in your visible set; unfollow
  to narrow it out. Sources you already created keep running.
- **Only selected providers** narrows the set to the followed providers
  (manual and extension sources stay visible).
- **Hidden sources** is a hard deny — the source never appears in
  Explore, radar, digests, saved-search runs, RSS or chat, whatever the
  other filters say.

Precedence is strongest-first: hidden sources, then selected-provider
mode, then the radar source picker, then per-search include/exclude.
User preferences never create or delete a job source.

## If a pack's content is missing

A version's pack bytes are derived data: the version row records the digest,
and the archive is cached beside it. If the archive is gone (a restored
database, a copied profile or a backup restored without uploads), **Sync now**
fetches and stores it again for the same digest (Git/index providers). A plan
preview in that state reports `PACK_ARCHIVE_MISSING` with the recovery step
instead of failing silently; for an **uploaded pack**, upload the zip again.

## Related

- [Add a job source](add-a-job-source.md) — create a source from the preset
  gallery once a provider is applied
- [Postings and search](postings-and-search.md) — what happens to postings
  after a source runs
