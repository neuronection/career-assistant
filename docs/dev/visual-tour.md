# Demo tour captures

How the README GIF, the screenshot gallery (`docs/SCREENSHOTS.md`) and
`docs/images/tour.manifest.json` are regenerated for Career Assistant —
the reproducible demo presentation embedded in the README, the docs and
the Neuronection website. The pipeline lives in `scripts/ui-capture/`
(family-standard vendored runner + this repo's config and scene catalog);
anyone can regenerate the exact same assets from a seeded demo instance.

## The demo instance

Captures always run against a demo instance: synthetic personas seeded by
`scripts/seed-demo.py` into an isolated demo database, with mock AI so
chat scenes are deterministic. Demo login: `wren.ashgrove@demo.career.local`
/ `DemoCareer!2026` (all demo personas share the password).

## Regenerating the tour

Four terminals (or a honcho file of your own):

```bash
# 1. seed the demo workspace (creates dev/demo-data/career.sqlite3)
bash scripts/ui-capture/seed-demo.sh

# 2. backend on :8100 against the demo DB, server identity, mock AI
#    (rate limiting off — scripted boots would otherwise 429 the auth
#    endpoint mid-run, as in the e2e harness; the demo instance is local)
cd backend && CAREER_DATABASE_URL="sqlite+aiosqlite:///$PWD/../dev/demo-data/career.sqlite3" \
  CAREER_IDENTITY_MODE=server CAREER_DEMO_MODE=true CAREER_MOCK_AI=1 CAREER_RATELIMIT_ENABLED=false \
  uv run uvicorn app.main:app --host 127.0.0.1 --port 8100

# 3. frontend on :3100 (vite proxies /api to :8100)
cd frontend && npm run dev

# 4. capture: seed check → screenshots → gallery → manifest → GIF
./scripts/capture_ui.sh
```

Single scene / strict mode / gallery-only rebuilds:

```bash
./scripts/capture_ui.sh --scene dashboard
./scripts/capture_ui.sh --viewport mobile
./scripts/capture_ui.sh --strict
./scripts/capture_ui.sh --gallery-only
```

Recommended system tools (otherwise the GIF step is skipped and PNGs stay
large): `pngquant`, `gifsicle`, `ffmpeg`.

## What gets committed

- `docs/images/*.png` + `docs/images/visual-tour.gif` +
  `docs/images/tour.manifest.json` — all generated, all committed.
- `docs/SCREENSHOTS.md` (+ `SCREENSHOTS.MOBILE.md` when mobile is
  captured) — the generated gallery, registered in `docs/docs-tree.json`.
- Scenes live in `scripts/ui-capture/scenes.mjs`: add a page = add an
  object; per-scene `narration` lines feed the future AI-video tour.

## After the first capture (one-time wiring)

1. Register the gallery in `docs/docs-tree.json` — a "Visual Tour" item
   (`file: "SCREENSHOTS.md"`) in the user guide's *Start here* category,
   and mirror it in `docs/user/README.md`.
2. Embed the GIF in `README.md` under the header badges:

   ```html
   <a href="docs/SCREENSHOTS.md"><img src="docs/images/visual-tour.gif" width="800" alt="Career Assistant visual tour"></a>
   ```

Recapture on every release and whenever the UI changes visibly —
screenshots are documentation and follow the same-commit rule.
