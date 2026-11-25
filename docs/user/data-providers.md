# Data providers

Admins manage the job-source **data providers** at
[Tools → Sources → Data providers](/settings/tools?section=sources). A
provider publishes versioned **packs** of presets (employer ATS tenants) and
public endpoint hints. Packs are data: the app fetches them, stores an
immutable content-addressed version, and nothing reaches the catalog until you
approve that exact digest and apply it.

## What ships with the app

- **Bundled presets** — 20 zero-config presets (17 Greek employer tenants and
  the three remote boards) at priority 0. They are applied at boot, enabled by
  default, and only change when the bundled pack changes.
- **Official Neuronection provider** — a disabled Git tile pinned to a released
  tag of the public
  [career-assistant-seeds](https://github.com/neuronection/career-assistant-seeds)
  repository. **Sync now** fetches its latest pack; approve and apply it when
  you want the official coverage on top of the bundled floor.

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

## Related

- [Add a job source](add-a-job-source.md) — create a source from the preset
  gallery once a provider is applied
- [Postings and search](postings-and-search.md) — what happens to postings
  after a source runs
