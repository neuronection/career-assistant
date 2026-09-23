# Troubleshooting

Common problems and their fixes. For self-hosting specifics, see
[Deployment](../dev/deployment.md).

## AI features answer `503`

A fresh install (or a fresh production deploy) starts **unconfigured**.
Add a provider in **Settings → AI Configuration** — see
[Getting started](getting-started.md#connect-an-ai-provider).

In development you can instead start the backend with the built-in mock
provider (`./scripts/run-dev.sh --mock-ai` or `MOCK_AI=1`). The mock can never
serve results in production.

## Upload returns `413`

The PDF exceeds the upload cap. Raise `MAX_UPLOAD_MB` **and** your reverse
proxy's body cap (nginx ships a 64 MB cap — keep it ≥ `MAX_UPLOAD_MB`). See
[Deployment](../dev/deployment.md).

## The container restarts in a loop

Check the logs for the boot-guard message:

```bash
docker compose -f docker/docker-compose.prod.yml logs app
```

The usual cause is a weak `JWT_SECRET` (production refuses to start with one).
See [Privacy and security](privacy-and-security.md#fail-safe-production-mode).

## Is the service healthy?

`GET /health` returns JSON liveness info. Wire your monitor to it.

## PDF export answers `503` or page counts say `unverified`

There is no print engine available. On Linux desktop packages the headless
Chromium shell is bundled; on Windows the app uses the system Edge/Chrome
channels. Probe a frozen install with:

```bash
careerassistant enginecheck
```

Without an engine, export falls back to the print view and page counts are
flagged `unverified` rather than guessed.

## The desktop window closed but the app is still running

That is the **tray** behaviour: closing the window keeps scheduled work alive.
Quit from the tray menu. If the tray icon is missing on Linux, install an
AppIndicator host — the app degrades gracefully without one.

## A second launch does not open a window

The single-instance lock focuses the running window instead of starting a
duplicate. If the running instance is unresponsive, quit it from the tray and
relaunch.

## AI key appears as `***`

That is the mask marker, not your key. Responses never return the real key;
sending `***` on update means "keep existing". See
[Privacy and security](privacy-and-security.md#ai-provider-keys).

## My CV page count does not match the preview

The **printed PDF is the page-count truth** — it is measured by the real print
engine, not estimated. If the export and the canvas disagree, trust the
exported PDF. See [CV Studio overview](cv-studio.md#honesty-tools).

## Still stuck?

- Search or open an issue:
  [GitHub Issues](https://github.com/neuronection/career-assistant/issues)
- Ask the community: [Discord](https://discord.com/invite/SZCXNTwv)
- Check [STATUS.md](../STATUS.md) for known limitations.
