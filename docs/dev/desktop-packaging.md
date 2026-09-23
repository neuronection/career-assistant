# Desktop packaging

The desktop app is the same backend + SPA frozen into a native package with
**PyInstaller**, launched through `python -m careerassistant`. Linux ships
`.deb` + AppImage; Windows ships a portable one-file `.exe`; releases are
tag-driven.

## Modes

`backend/careerassistant/__main__.py` is the dispatcher:

```
python -m careerassistant [app|web|seed|backup|restore ZIP]
python -m careerassistant app --tray     # background auto-start
python -m careerassistant enginecheck    # PDF engine health probe
```

| Mode | Behaviour |
|---|---|
| `app` (default) | pywebview window over a local loopback server, with tray + background mode |
| `app --tray` | Tray-only boot (for auto-start on login) |
| `web` | Fixed loopback port + system browser (no window shell) |
| `seed` | Apply migrations + idempotent starter catalog, then exit |
| `backup` / `restore ZIP` | Local profile backup/restore |
| `enginecheck` | Print one PDF through the engine and report page-count health |

All modes except `enginecheck` bootstrap the local profile first: platform
data dir, migrations, and (unless `CAREER_SKIP_SEED=1`) seeding.

## Building Linux packages

```bash
(cd frontend && npm ci && npm run build)          # the spec requires frontend/dist
backend/venv/bin/pyinstaller --clean --noconfirm packaging/career-assistant.spec

packaging/build-linux.sh [bundle|deb|appimage|all] [version]
```

- `bundle` — the PyInstaller onedir tree at `backend/dist/careerassistant`.
- `deb` — bundle + `.deb` (needs `dpkg-deb`; runtime needs
  `libwebkit2gtk-4.1`).
- `appimage` — bundle + AppImage (needs `appimagetool`; self-contained).
- `all` — the default.

The spec reads the app version from `backend/app/__init__.py`, so a release
tag must match it. Env overrides: `CA_ONEFILE=1|0` (default one-file on
Windows/macOS, onedir on Linux), `CA_CONSOLE=1` to keep a console.

## The PDF engine

CV export and page counting need a print engine (plan 76). The build installs
`requirements-pdf.txt` and `playwright install chromium --only-shell`, and the
headless shell is bundled into Linux packages. On Windows the frozen app uses
the **system Edge/Chrome channels** instead of bundling Chromium.

Without an engine, export answers `503` (print-view fallback) and page counts
are flagged `unverified` — capability detection, never a hard dependency.
Probe a frozen install with `careerassistant enginecheck`.

## Releases

`.github/workflows/release.yml` triggers on `v*` tags:

1. **Verify the tag matches the app version** (fails otherwise).
2. **Linux job** (`ubuntu-22.04`): build frontend, install PDF deps, build
   `.deb` + AppImage, smoke-test the frozen bundle (headless web mode + a
   desktop launch under xvfb), upload artifacts and publish the GitHub
   Release. Stable-name download aliases are created
   (`CareerAssistant-x86_64.AppImage`, `careerassistant_amd64.deb`).
3. **Windows job** (`windows-latest`): build the one-file exe, smoke-test
   headless web mode, rename and upload.

Use `scripts/version_manager.py` for the bump + tag flow (see the
`family-release` skill).

## CI workflows

| Workflow | Purpose |
|---|---|
| `ci.yml` | pytest (Postgres + serial SQLite desktop job), frontend build + vitest, ruff, docs-sync |
| `release.yml` | Tag-driven packaging and GitHub Release |
| `ai-alignment.yml` | The AI architecture gate (`scripts/check-ai-alignment.sh`) |
| `drift-audit.yml` | assistant-ui adoption drift |
| `gitleaks.yml` | Secret scanning |

## Related

- [Deployment](deployment.md) — the server-side stack
- [Development workflow](development.md) — the verification gates
- [User: Desktop app](../user/desktop-app.md)
