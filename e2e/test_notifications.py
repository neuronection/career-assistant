"""Notification reach (plan 117): email double opt-in through the fake
transport, webhook test delivery to a loopback receiver, and the calendar
token lifecycle (mint → subscribe → revoke → 404)."""

import json
import os
import re
import threading
import time
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from conftest import API, BASE_URL, api_headers

MAIL_DIR = Path(os.environ.get("E2E_MAIL_DIR", "/tmp/career-e2e-mail"))


def _mail_files() -> set[Path]:
    return set(MAIL_DIR.glob("*.eml"))


def _read_message(path: Path) -> tuple[str, str]:
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    part = message.get_body(preferencelist=("plain",))
    body = part.get_content() if part is not None else ""
    return str(message.get("Subject") or ""), str(body)


def _wait_for_mail(before: set[Path], timeout: float = 20.0) -> tuple[str, str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        fresh = sorted(_mail_files() - before)
        if fresh:
            newest = max(fresh, key=lambda path: path.stat().st_mtime)
            return _read_message(newest)
        time.sleep(0.2)
    raise AssertionError(f"no mail arrived in {MAIL_DIR}")


class _HookReceiver:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, str], dict]] = []
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 — stdlib handler name
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode("utf-8")
                headers = {key.lower(): value for key, value in self.headers.items()}
                receiver.requests.append((self.path, headers, json.loads(body or "{}")))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

            def log_message(self, *_args) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "_HookReceiver":
        self.thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.server.shutdown()
        self.server.server_close()


def _verify_email(page, address: str) -> None:
    before = _mail_files()
    response = page.request.put(
        f"{API}/notifications/channels/email",
        data=json.dumps({"enabled": True, "address": address, "digest_mode": False}),
        headers=api_headers({"Content-Type": "application/json"}),
    )
    assert response.ok, response.text()
    _subject, body = _wait_for_mail(before)
    match = re.search(r"verify=([A-Za-z0-9_\-]+)", body)
    assert match is not None, body
    verified = page.request.post(
        f"{API}/notifications/channels/email/verify",
        data=json.dumps({"token": match.group(1)}),
        headers=api_headers({"Content-Type": "application/json"}),
    )
    assert verified.ok, verified.text()
    assert verified.json()["verified"] is True


def test_email_verification_and_test_delivery(page) -> None:
    transport = page.request.put(
        f"{API}/admin/notifications/email",
        data=json.dumps(
            {
                "host": "smtp.invalid",
                "port": 587,
                "from_address": "career@example.test",
                "from_name": "Career Assistant",
                "starttls": True,
            }
        ),
        headers=api_headers({"Content-Type": "application/json"}),
    )
    assert transport.ok, transport.text()
    assert transport.json()["password_set"] is False

    _verify_email(page, "e2e-notify@example.test")
    config = page.request.get(
        f"{API}/notifications/channels/email", headers=api_headers()
    ).json()
    assert config["verified"] is True

    before = _mail_files()
    tested = page.request.post(
        f"{API}/notifications/channels/email/test", headers=api_headers()
    )
    assert tested.ok, tested.text()
    assert tested.json()["status"] == "delivered"
    subject, _body = _wait_for_mail(before)
    assert "Career Assistant test email" in subject


def test_webhook_test_delivery_uses_the_sealed_secret(page) -> None:
    with _HookReceiver() as receiver:
        saved = page.request.put(
            f"{API}/notifications/channels/webhook",
            data=json.dumps(
                {
                    "enabled": True,
                    "url": f"http://127.0.0.1:{receiver.port}/hook",
                    "template": "slack",
                    "secret": "e2e-hook-secret",
                }
            ),
            headers=api_headers({"Content-Type": "application/json"}),
        )
        assert saved.ok, saved.text()
        assert saved.json()["secret_set"] is True and "secret" not in saved.json()

        tested = page.request.post(
            f"{API}/notifications/channels/webhook/test", headers=api_headers()
        )
        assert tested.ok, tested.text()
        assert tested.json()["status"] == "delivered"
        assert receiver.requests, "webhook receiver got no request"
        _path, headers, payload = receiver.requests[0]
        assert headers["x-career-webhook-token"] == "e2e-hook-secret"
        assert "Channel test" in payload["text"]


def test_calendar_token_lifecycle(page) -> None:
    minted = page.request.post(
        f"{API}/me/feed-tokens",
        data=json.dumps({"kind": "ics", "scope": {}}),
        headers=api_headers({"Content-Type": "application/json"}),
    )
    assert minted.ok, minted.text()
    token = minted.json()["token"]
    token_id = minted.json()["id"]

    subscribed = page.request.get(f"{API}/me/calendar.ics?token={token}")
    assert subscribed.ok, subscribed.text()
    assert subscribed.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in subscribed.text()

    listing = page.request.get(f"{API}/me/feed-tokens", headers=api_headers())
    assert listing.ok
    rows = listing.json()
    assert any(row["id"] == token_id for row in rows)
    assert all("token" not in row and "token_hash" not in row for row in rows)

    revoked = page.request.delete(
        f"{API}/me/feed-tokens/{token_id}", headers=api_headers()
    )
    assert revoked.status == 204
    assert page.request.get(f"{API}/me/calendar.ics?token={token}").status == 404


def test_settings_surfaces_the_new_channels(page) -> None:
    page.goto(f"{BASE_URL}/settings/notifications")
    page.get_by_test_id("email-settings").wait_for(state="visible", timeout=20_000)
    page.get_by_test_id("webhook-settings").wait_for(state="visible", timeout=20_000)
    page.get_by_test_id("feed-tokens").wait_for(state="visible", timeout=20_000)
    page.get_by_test_id("mint-ics").wait_for(state="visible", timeout=20_000)
    page.get_by_test_id("kind-followup_due-email").wait_for(state="visible", timeout=20_000)
