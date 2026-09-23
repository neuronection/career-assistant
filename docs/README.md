# Career Assistant documentation

This directory is the project's manual, split by audience. It is the
canonical, public documentation surface: everything here ships with the
repository and is published to the demonstration website's docs section.

| Audience | Start here | What it covers |
|---|---|---|
| **Users** | [user/README.md](user/README.md) | Install, onboard, explore jobs, matching, postings, Autopilot, universities, growth, CV Studio, chat, interviews, settings, privacy, troubleshooting |
| **Developers** | [dev/README.md](dev/README.md) | Architecture, development workflow, data model, REST API, AI layer, connectors, scheduler, CV engine, frontend, testing, migrations, deployment, packaging |
| **Everyone** | [STATUS.md](STATUS.md) | Single source of truth for what exists and the current phase |

The [root README](https://github.com/neuronection/career-assistant/blob/main/README.md) is the short marketing overview; this
directory is the manual. The [feature catalog](user/features.md) is the
exhaustive "everything, as built" tour.

## The docs tree

`docs-tree.json` in this directory is the **machine-readable navigation
tree** — the repo-level source of truth for how these pages are grouped and
ordered. Both trees (`user`, `dev`) are described there with categories,
icons and one-line descriptions per page, so the website's docs section (or
any other renderer) can build navigation without guessing from filenames.

```
docs/
├── README.md          ← this index
├── STATUS.md          ← what exists / current phase
├── docs-tree.json     ← nav tree (audience → category → page)
├── user/              ← end-user guides
└── dev/               ← developer & operator guides
```

### `docs-tree.json` shape

```jsonc
{
  "version": 1,
  "project": "career-assistant",
  "audiences": [
    {
      "id": "user",                       // directory name under docs/
      "title": "User Guide",
      "description": "…",
      "categories": [
        {
          "id": "start",
          "title": "Start here",
          "icon": "Play",                 // lucide icon name
          "items": [
            {
              "id": "getting-started",
              "file": "user/getting-started.md",  // path relative to docs/
              "title": "Getting started",
              "description": "One-line SEO/listing description."
            }
          ]
        }
      ]
    }
  ]
}
```

## Documentation rules

- **Code and docs move together.** A behavior, schema, API or UI change
  updates its page in the same commit as the code. User-visible changes also
  add a `## [Unreleased]` entry to [CHANGELOG.md](https://github.com/neuronection/career-assistant/blob/main/CHANGELOG.md)
  (CI-enforced by `scripts/check-changelog.sh`).
- **One page, one topic.** Pages are kebab-case `.md` files under `user/` or
  `dev/`; the first `H1` is the title (the website renders its own heading and
  derives the description from the first paragraph).
- **Relative links only between docs** (`../dev/architecture.md`); the website
  rewrites them to route links. Absolute links point at GitHub.
- **The tree is the index.** Adding, renaming or moving a page means updating
  `docs-tree.json` (and the website's ingestion manifest) in the same change.
- **User guides describe what the UI says.** If a guide and the interface
  disagree, the interface wins and the guide is a bug.
- **No secrets, no unverified claims.** Never paste keys, tokens or private
  hostnames; never document a feature as shipped until it is.
