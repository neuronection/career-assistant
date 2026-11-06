"""S14 browser e2e (plan 20 residual): the §4.5 instance-mode control.

The e2e server boots the `server` entrypoint (identity-auth §4 — always
authenticated), which is exactly the control's blocked state: "Remove
login" must be offered NOWHERE on a server instance, the blocked reason
must say so, and the transition must stay disabled even with a password
and the acknowledgement filled in. The desktop `open → authenticated`
half stays pinned by the wiring/contract suites (a browser cannot boot
the desktop shell here).
"""

from conftest import API, BASE_URL, api_headers


def _instance_config() -> dict:
    import urllib.request

    request = urllib.request.Request(f"{API}/instance/config")
    with urllib.request.urlopen(request) as response:
        import json

        return json.load(response)


def test_server_instance_never_offers_remove_login(page) -> None:
    config = _instance_config()
    assert config["identity_mode"] == "server", "e2e shape: server entrypoint"
    assert config["auth_mode"] == "authenticated"

    page.goto(f"{BASE_URL}/settings/users")
    page.wait_for_selector('[data-testid="settings-users"]')

    # The panel renders the authenticated state and the §4.5 blocked
    # reason — the server entrypoint can never go open.
    panel = page.locator('[data-testid="settings-users"]')
    panel.get_by_text("Login required").wait_for(state="visible", timeout=15_000)
    panel.get_by_text("Server instances always require login.").wait_for(state="visible")

    # The "Disable login" transition stays disabled even when the form is
    # fully filled (blocked beats valid input — §4.5).
    remove = panel.get_by_role("button", name="Disable login")
    remove.wait_for(state="visible")
    assert remove.is_disabled(), "server instances must not offer Disable login"

    panel.get_by_label("Password", exact=False).first.fill("a-long-enough-password")
    panel.get_by_role("checkbox").check()
    assert remove.is_disabled(), "blocked state beats a filled form"


def test_direct_mode_flip_refused_with_audit(page) -> None:
    """The API half of the same guarantee, with the CORRECT password so
    the §4.4 server rule is what refuses (a wrong password would 403
    earlier on the generic credential check): fail-closed; the UI block
    is defense-in-depth, never the boundary."""
    import json
    import os

    password = os.environ.get("E2E_USER_PASSWORD", "e2e-supersecret1")
    response = page.request.patch(
        f"{API}/admin/instance",
        headers={**api_headers(), "Content-Type": "application/json"},
        data=json.dumps({"auth_mode": "open", "password": password}),
    )
    assert response.status == 403
    assert "never run open" in response.text()
