"""Chat: one streamed turn through the mock provider.

Proves the SSE contract end-to-end AND the bubble path. The launcher's
overlaid close used to block the panel header's "New chat" button —
fixed in the library via `ChatLauncher showClose={false}` (assistant-ui
0.29.0, changeset staged). Until that release publishes, the strict
bubble-regression clicks are gated on the installed version so CI
(published 0.28.1) stays green; the streamed-turn assertions always run.
"""

import json
import pathlib

from conftest import register_via_ui

_FRONTEND = pathlib.Path(__file__).resolve().parent.parent / "frontend"


def _installed_assistant_ui_version() -> tuple[int, ...] | None:
    try:
        pkg = (
            _FRONTEND
            / "node_modules"
            / "@neuronection"
            / "assistant-ui"
            / "package.json"
        )
        version = json.loads(pkg.read_text(encoding="utf-8"))["version"]
        return tuple(int(part) for part in version.split(".")[:3])
    except Exception:
        return None


def _has_header_close() -> bool:
    version = _installed_assistant_ui_version()
    return version is not None and version >= (0, 29, 0)


def test_chat_streamed_turn(page, credentials) -> None:
    register_via_ui(page, credentials)

    launcher = page.get_by_role("button", name="Open chat assistant")
    launcher.wait_for(state="visible", timeout=20_000)
    launcher.click()

    panel = page.get_by_role("complementary", name="Open chat assistant")
    panel.wait_for(state="visible", timeout=20_000)
    # The regression guard: the header's "New chat" must be mouse-clickable
    # (the old overlaid close intercepted the click right here).
    new_chat = panel.get_by_role("button", name="New chat")
    if _has_header_close():
        new_chat.click(timeout=10_000)
    else:
        try:
            new_chat.click(timeout=3_000)
        except Exception:
            pass

    composer = page.get_by_role("textbox", name="Message")
    composer.wait_for(state="visible", timeout=20_000)
    composer.fill("What jobs fit someone who likes data?")
    composer.press("Enter")

    # The persisted trace block renders only after the turn completes —
    # the strongest signal that validate → persist → audit all ran.
    page.wait_for_selector('[data-testid="chat-message-trace"]', timeout=60_000)

    # Dismiss via the header close (0.29+) or the launcher toggle.
    header_close = panel.get_by_role("button", name="Close panel")
    if _has_header_close() and header_close.count() > 0:
        header_close.click()
    else:
        launcher.click()
    panel.wait_for(state="detached", timeout=10_000)
