# Desktop app

The desktop app runs Career Assistant as a local application: a pywebview
window with a system tray, a SQLite database, and everything under your OS
data directory. No Docker, no Postgres, no browser required.

## Running it

Download a prebuilt package from the
[Releases](https://github.com/neuronection/career-assistant/releases) page
(Windows `.exe`, Linux `.deb` or AppImage), or run it from source:

```bash
cd backend
python -m venv venv && ./venv/bin/pip install -r requirements-desktop.txt
./venv/bin/python -m careerassistant              # window + tray (default)
./venv/bin/python -m careerassistant app --tray   # tray-only boot (auto-start)
./venv/bin/python -m careerassistant web          # loopback server + browser
./venv/bin/python -m careerassistant seed         # migrations + starter catalog only
```

Linux needs `libgtk-3`, `libwebkit2gtk-4.1` and an AppIndicator host (the
tray degrades gracefully without one).

## First launch

First launch creates a strong `secret.key`, applies migrations and seeds the
starter catalog automatically (opt out with `CAREER_SKIP_SEED=1`). AI
providers are configured in-app — for a fully local setup, point a provider at
Ollama (`http://localhost:11434/v1`) or LM Studio.

## The tray

Closing the window keeps the app running in the tray (after a first-run opt-in
prompt):

- **Scheduled searches, syncs and alerts continue** in the background.
- **Native toasts** arrive through the desktop notification channel, honoring
  quiet hours and opening the relevant item on click.
- **Sync-now and saved-search controls** live in the tray menu.
- **Misfired runs catch up on boot** (for example after the machine slept).

Quit from the tray menu. A **second launch focuses the running window**
instead of starting a duplicate (single-instance lock), and **auto-start on
login** is opt-in from the tray menu and boots tray-only.

## The PDF engine

CV export and page counting use a real print engine. Linux packages bundle
the headless Chromium shell; the Windows exe uses the system Edge/Chrome
channels. Without an engine, export answers `503` (with a print-view fallback)
and page counts are flagged `unverified` — a capability, never a hard
dependency.

To check a frozen install:

```bash
careerassistant enginecheck
```

## Related

- [Getting started](getting-started.md) — install paths for both modes
- [Notifications and scheduler](notifications-and-scheduler.md) — what keeps running
- [Desktop packaging](../dev/desktop-packaging.md) — the developer view
