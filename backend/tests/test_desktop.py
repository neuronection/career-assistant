"""Phase 30 — desktop background mode: single-instance, close-to-tray,
auto-start, the desktop notification channel and the shutdown drain."""

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import _engine, _session_factory


@pytest.fixture
async def kinds(db):
    """The launch notification kinds (truncated by clean_db)."""
    from app.seeds.run import seed_notification_kinds

    return await seed_notification_kinds(db)


# ------------------------------------------------------------- single instance


async def test_second_launch_focuses_first(tmp_path: Path):
    from app.desktop.single_instance import SingleInstance

    focused: list[bool] = []
    first = SingleInstance(tmp_path, on_focus_request=lambda: focused.append(True))
    assert first.acquire() is True
    try:
        second = SingleInstance(tmp_path, on_focus_request=lambda: None)
        # The failed acquire's handshake probe IS the focus ping.
        assert second.acquire() is False
        for _ in range(50):  # the listener thread delivers asynchronously
            if focused:
                break
            await asyncio.sleep(0.02)
        assert focused == [True]
    finally:
        first.release()


async def test_stale_lock_recovered(tmp_path: Path):
    """Dead PID + dead socket ⇒ the lock is reclaimed, not honoured."""
    from app.desktop.single_instance import SingleInstance

    (tmp_path / "app.lock").write_text('{"pid": 999999999, "socket": "x"}')
    (tmp_path / "app.sock").write_text("")
    instance = SingleInstance(tmp_path, on_focus_request=lambda: None)
    try:
        assert instance.acquire() is True
    finally:
        instance.release()


async def test_release_removes_lock_files(tmp_path: Path):
    from app.desktop.single_instance import SingleInstance

    instance = SingleInstance(tmp_path, on_focus_request=lambda: None)
    instance.acquire()
    instance.release()
    assert not (tmp_path / "app.sock").exists()
    assert not (tmp_path / "app.lock").exists()


# ------------------------------------------------------------ desktop settings


def test_desktop_settings_roundtrip(tmp_path: Path):
    from app.desktop.settings import DesktopSettings

    loaded = DesktopSettings.load(tmp_path)
    assert loaded.close_to_tray is None  # unchosen: first-run prompt
    assert loaded.autostart is False

    loaded.close_to_tray = True
    loaded.autostart = True
    loaded.save(tmp_path)
    reloaded = DesktopSettings.load(tmp_path)
    assert reloaded.close_to_tray is True
    assert reloaded.autostart is True


def test_should_hide_on_close(tmp_path: Path):
    from app.desktop.settings import DesktopSettings, should_hide_on_close

    assert should_hide_on_close(tmp_path) is False  # unchosen closes outright
    settings = DesktopSettings.load(tmp_path)
    settings.close_to_tray = True
    settings.save(tmp_path)
    assert should_hide_on_close(tmp_path) is True


# ------------------------------------------------------------------- autostart


def test_autostart_written_and_removed(tmp_path: Path):
    from app.desktop import autostart

    environ = {"XDG_CONFIG_HOME": str(tmp_path)}
    assert autostart.is_autostart_enabled(environ) is False
    assert autostart.set_autostart(True, environ) is True
    path = tmp_path / "autostart" / "career-assistant.desktop"
    assert path.is_file()
    body = path.read_text(encoding="utf-8")
    assert "--tray" in body
    assert "[Desktop Entry]" in body
    assert autostart.is_autostart_enabled(environ) is True

    assert autostart.set_autostart(False, environ) is True
    assert not path.exists()
    assert autostart.is_autostart_enabled(environ) is False


# ------------------------------------------------------ desktop channel funnel


async def test_emit_dispatches_to_registered_channel(db, kinds):
    from app.services import notification_channels
    from app.services.engagement_service import EngagementService

    seen: list[dict] = []

    async def _dispatcher(user_id, kind, title, body, payload, severity):
        seen.append(
            {
                "user_id": user_id,
                "kind": kind,
                "title": title,
                "body": body,
                "payload": payload,
                "severity": severity,
            }
        )

    notification_channels.register_dispatcher(_dispatcher)
    try:
        user_id = await _make_user(db, "dispatch@example.com")
        notification = await EngagementService(db).emit(
            user_id,
            "fit_threshold",
            title="Strong fit",
            body=" reached 8/10",
            payload={"link": "/jobs/ENG-1"},
            dedup_key=f"fit:{user_id}",
        )
        assert notification is not None
        assert len(seen) == 1
        assert seen[0]["user_id"] == user_id
        assert seen[0]["kind"] == "fit_threshold"
        assert seen[0]["title"] == "Strong fit"
        assert seen[0]["payload"]["link"] == "/jobs/ENG-1"
        await db.rollback()  # release row locks (clean_db TRUNCATEs next)
    finally:
        notification_channels.unregister_dispatcher()
    assert notification_channels.has_dispatcher() is False


async def test_dispatch_dedup_suppressed_means_no_toast(db, kinds):
    """Dedup collapse ⇒ no inbox row ⇒ no toast (single funnel)."""
    from app.services import notification_channels
    from app.services.engagement_service import EngagementService

    calls: list[int] = []
    notification_channels.register_dispatcher(_counting_dispatcher(calls))
    try:
        user_id = await _make_user(db, "dedup@example.com")
        service = EngagementService(db)
        first = await service.emit(
            user_id,
            "digest_ready",
            title="Weekly digest",
            dedup_key=f"digest:{user_id}",
        )
        second = await service.emit(
            user_id,
            "digest_ready",
            title="Weekly digest",
            dedup_key=f"digest:{user_id}",
        )
        assert first is not None and second is None
        assert len(calls) == 1
        await db.rollback()
    finally:
        notification_channels.unregister_dispatcher()


def _counting_dispatcher(calls):
    async def _dispatch(*_args):
        calls.append(1)

    return _dispatch


async def _make_user(db, email: str) -> uuid.UUID:
    """A real user row (notifications FK requires one)."""
    from app.models.user_model import User

    user = User(email=email, password_hash="test-only", full_name="T")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


class _FakeBridge:
    def __init__(self, available: bool = True):
        self.toasts: list[dict] = []
        self.available = available

    def notify(self, *, title, body, kind, severity="info", link=""):
        if not self.available:
            return False
        self.toasts.append({"title": title, "body": body, "kind": kind, "link": link})
        return True

    def show_and_focus(self):
        return None


async def test_quiet_hours_suppress_toast_but_inbox_filled(db, kinds):
    """Dispatch guard (desktop channel): quiet hours kill the toast, never
    the inbox row."""
    from app.desktop import notifier
    from app.services import notification_channels
    from app.services.engagement_service import EngagementService

    bridge = _FakeBridge()
    notifier.register_desktop_channel(bridge)
    try:
        user_id = await _make_user(db, "quiet@example.com")
        await EngagementService(db).upsert_preferences(
            user_id,
            desktop_channel_enabled=True,
            quiet_hours={"start": "00:00", "end": "23:59"},
        )
        row = await EngagementService(db).emit(
            user_id, "fit_threshold", title="Strong fit"
        )
        assert row is not None  # inbox filled
        assert bridge.toasts == []  # toast suppressed at dispatch

        await EngagementService(db).upsert_preferences(
            user_id, desktop_channel_enabled=True, quiet_hours=None
        )
        await EngagementService(db).emit(user_id, "fit_threshold", title="Strong fit 2")
        assert len(bridge.toasts) == 1
        assert bridge.toasts[0]["link"] == ""
        await db.rollback()
    finally:
        notification_channels.unregister_dispatcher()


async def test_channel_disabled_means_no_dispatch(db, kinds):
    from app.desktop import notifier
    from app.services import notification_channels
    from app.services.engagement_service import EngagementService

    bridge = _FakeBridge()
    notifier.register_desktop_channel(bridge)
    try:
        user_id = await _make_user(db, "disabled@example.com")
        await EngagementService(db).upsert_preferences(
            user_id, desktop_channel_enabled=False
        )
        row = await EngagementService(db).emit(
            user_id, "fit_threshold", title="Strong fit"
        )
        assert row is not None
        assert bridge.toasts == []
        await db.rollback()
    finally:
        notification_channels.unregister_dispatcher()


async def test_dispatcher_failure_does_not_break_emit(db, kinds):
    from app.services import notification_channels
    from app.services.engagement_service import EngagementService

    async def _broken(*_args):
        raise RuntimeError("channel down")

    notification_channels.register_dispatcher(_broken)
    try:
        user_id = await _make_user(db, "broken@example.com")
        row = await EngagementService(db).emit(
            user_id, "fit_threshold", title="Strong fit"
        )
        assert row is not None
        await db.rollback()
    finally:
        notification_channels.unregister_dispatcher()


def test_within_quiet_hours_overnight_window():
    from datetime import datetime, timezone

    from app.services.notification_channels import within_quiet_hours

    quiet = {"start": "22:00", "end": "07:00"}
    late = datetime(2026, 8, 31, 23, 0, tzinfo=timezone.utc)
    early = datetime(2026, 8, 31, 6, 0, tzinfo=timezone.utc)
    noon = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
    assert within_quiet_hours(quiet, late) is True
    assert within_quiet_hours(quiet, early) is True
    assert within_quiet_hours(quiet, noon) is False
    assert within_quiet_hours(None, late) is False
    assert within_quiet_hours({"start": "bad", "end": "07:00"}, late) is False


# ------------------------------------------------------- preferences endpoints


async def test_preferences_default_then_update(client, auth_headers):
    response = await client.get(
        "/api/v1/notifications/preferences", headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json() == {"desktop_channel_enabled": True, "quiet_hours": None}

    updated = await client.put(
        "/api/v1/notifications/preferences",
        json={
            "desktop_channel_enabled": False,
            "quiet_hours": {"start": "22:00", "end": "07:00"},
        },
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json() == {
        "desktop_channel_enabled": False,
        "quiet_hours": {"start": "22:00", "end": "07:00"},
    }

    cleared = await client.put(
        "/api/v1/notifications/preferences",
        json={"desktop_channel_enabled": True, "quiet_hours": None},
        headers=auth_headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["quiet_hours"] is None


async def test_preferences_reject_bad_quiet_hours(client, auth_headers):
    response = await client.put(
        "/api/v1/notifications/preferences",
        json={
            "desktop_channel_enabled": True,
            "quiet_hours": {"start": "25:00", "end": "07:00"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


# ---------------------------------------------------------- bootstrap channels


async def test_bootstrap_declares_web_channels(client, auth_headers):
    from app.core.config import settings

    assert settings.DESKTOP_MODE is False
    response = await client.get("/api/v1/me/bootstrap", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["notification_channels"] == ["in_app", "browser"]


async def test_bootstrap_declares_desktop_channels(client, auth_headers, monkeypatch):
    from app.core.config import settings
    from app.services import notification_channels

    monkeypatch.setattr(settings, "DESKTOP_MODE", True)
    assert notification_channels.available_channels() == ["in_app", "desktop"]
    response = await client.get("/api/v1/me/bootstrap", headers=auth_headers)
    assert response.json()["notification_channels"] == ["in_app", "desktop"]


# -------------------------------------------------------------- tray pure math


def test_badge_and_icon_states():
    from app.desktop.tray import TrayStatus, badge_label, icon_state

    assert icon_state(TrayStatus()) == "idle"
    assert icon_state(TrayStatus(sync_running=True)) == "sync"
    assert icon_state(TrayStatus(unread=3)) == "unread"
    assert icon_state(TrayStatus(unread=2, sync_running=True)) == "sync"
    assert badge_label(0) is None
    assert badge_label(7) == "7"
    assert badge_label(10) == "9+"


def test_menu_model_shape():
    from app.desktop.tray import build_menu_model

    menu = build_menu_model(
        saved_searches=[{"schedule_id": "s1", "label": "qa", "enabled": True}],
        notifications=[{"id": "n1", "title": "Strong fit"}],
        unread=4,
        close_to_tray=True,
        autostart=False,
    )
    ids = [item["id"] for item in menu]
    assert ids[:2] == ["open", "sync_now"]
    assert "notifications" in ids and "quit" in ids
    notifications = next(item for item in menu if item["id"] == "notifications")
    assert notifications["label"] == "Notifications (4)"
    assert {"id": "notification:n1", "label": "Strong fit"} in notifications["items"]
    assert {"id": "notifications:mark_read", "label": "Mark all read"} in (
        notifications["items"]
    )
    searches = next(item for item in menu if item["id"] == "saved_searches")
    assert {"id": "search:s1:run", "label": "Run now — qa"} in searches["items"]
    assert {"id": "search:s1:toggle", "label": "Disable qa"} in searches["items"]
    assert {
        "id": "toggle_close_to_tray",
        "label": "Close to tray",
        "checked": True,
    } in menu
    assert {
        "id": "toggle_autostart",
        "label": "Start on login",
        "checked": False,
    } in menu


# ---------------------------------------------------------- tray actions (API)


class _FocusBridge:
    def show_and_focus(self):
        return None


def _tray_actions():
    from app.desktop.tray import TrayActions

    factory = async_sessionmaker(
        bind=_engine, class_=AsyncSession, expire_on_commit=False
    )
    return TrayActions(factory, _FocusBridge())


async def _first_admin_id():
    from app.models.user_model import User

    async with _session_factory() as db:
        rows = await db.execute(select(User.id).where(User.is_admin.is_(True)))
        return rows.scalars().first()


async def test_tray_actions_use_admin_inbox(db, client, auth_headers, kinds):
    """First registered user is admin ⇒ the tray reads their inbox."""
    from app.services.engagement_service import EngagementService

    other_id = await _make_user(db, "other@example.com")
    await EngagementService(db).emit(other_id, "fit_threshold", title="other")
    admin_id = await _first_admin_id()
    await EngagementService(db).emit(admin_id, "fit_threshold", title="yours")
    await db.commit()

    actions = _tray_actions()
    items, unread = await actions.notifications(limit=5)
    assert [item["title"] for item in items] == ["yours"]
    assert unread == 1

    marked = await actions.mark_all_read()
    assert marked == 1
    _items, unread = await actions.notifications(limit=5)
    assert unread == 0


async def test_tray_sync_now_and_saved_search(db, client, auth_headers, kinds):
    """Sync-now + run/toggle hit the same scheduler service the API uses."""
    from app.services.scheduler.runner import SchedulerService

    await SchedulerService(db).ensure_system_schedules()

    recorded = await client.post(
        "/api/v1/me/searches",
        json={"scope": "postings", "query": "qa", "filters": {}, "result_count": 0},
        headers=auth_headers,
    )
    search_id = recorded.json()["id"]
    scheduled = await client.put(
        f"/api/v1/me/searches/{search_id}/schedule",
        json={"trigger": {"type": "interval", "params": {"every_minutes": 60}}},
        headers=auth_headers,
    )
    assert scheduled.status_code == 200

    actions = _tray_actions()
    searches = await actions.saved_searches()
    assert len(searches) == 1
    assert searches[0]["label"] == "qa"
    assert searches[0]["enabled"] is True

    await actions.toggle_saved_search(searches[0]["schedule_id"], False)
    searches = await actions.saved_searches()
    assert searches[0]["enabled"] is False

    await actions.run_saved_search(searches[0]["schedule_id"])

    assert await actions.sync_now() >= 1


async def test_tray_status_counts(db, client, auth_headers, kinds):
    from app.desktop.tray import TrayActions
    from app.services.engagement_service import EngagementService

    admin_id = await _first_admin_id()
    await EngagementService(db).emit(admin_id, "fit_threshold", title="yours")
    await db.commit()

    factory = async_sessionmaker(
        bind=_engine, class_=AsyncSession, expire_on_commit=False
    )
    status = await TrayActions(factory, _FocusBridge()).tray_status()
    assert status.unread == 1
    assert status.sync_running is False


# ----------------------------------------------------- contract: same endpoints


async def test_tray_endpoints_contract(client, auth_headers):
    """The HTTP endpoints the tray relies on behave as the web UI expects."""
    listed = await client.get("/api/v1/notifications", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json() == {"items": [], "unread_count": 0}

    marked = await client.post(
        "/api/v1/notifications/read", json={"ids": []}, headers=auth_headers
    )
    assert marked.status_code == 200 and marked.json() == {"marked": 0}

    prefs = await client.get("/api/v1/notifications/preferences", headers=auth_headers)
    assert prefs.status_code == 200

    schedules = await client.get("/api/v1/me/schedules", headers=auth_headers)
    assert schedules.status_code == 200
    assert any(s["kind"] == "user_checkin" for s in schedules.json())


# ----------------------------------------------------------------- queue drain


async def test_quit_drains_queue(db):
    """Graceful quit: queued jobs execute before the workers stop."""
    from app.models.background_job_model import BackgroundJob
    from app.services.job_worker import drain_queue, enqueue

    job = await enqueue(db, "no_such_type", {}, max_attempts=1)
    drained = await asyncio.wait_for(drain_queue(db), timeout=10)
    assert drained == 1
    await db.refresh(job)
    assert job.status == "failed"  # executed (unknown type fails terminally)
    rows = await db.execute(
        select(BackgroundJob).where(BackgroundJob.status == "queued")
    )
    assert rows.scalars().all() == []


async def test_drain_empty_queue_is_noop(db):
    from app.services.job_worker import drain_queue

    assert await asyncio.wait_for(drain_queue(db), timeout=5) == 0


# ------------------------------------------------------------ fallback + args


async def test_os_fallback_without_notify_send_is_noop(monkeypatch):
    import app.desktop.notifier as notifier

    monkeypatch.setattr(notifier.shutil, "which", lambda name: None)
    notifier._os_fallback("title", "body")  # must not raise


def test_main_app_tray_flag(monkeypatch):
    import app.backups as backups
    import app.local as local_mod
    import app.shell as shell_mod
    import careerassistant.__main__ as entry

    called: dict = {}

    monkeypatch.setattr(local_mod, "default_data_dir", Path)
    monkeypatch.setattr(local_mod, "bootstrap_environment", lambda *_: {})
    monkeypatch.setattr(local_mod, "run_migrations", lambda: None)
    monkeypatch.setattr(local_mod, "seed_catalog_data", lambda: None)
    monkeypatch.setattr(backups, "verify_or_repair_database", lambda *_: "ok")
    monkeypatch.setattr(backups, "backup_if_due", lambda *_: None)

    def fake_run(*, tray_only=False):
        called["tray_only"] = tray_only

    monkeypatch.setattr(shell_mod, "run", fake_run)
    try:
        assert entry.main(["app", "--tray"]) == 0
        assert called["tray_only"] is True

        called.clear()
        assert entry.main(["app"]) == 0
        assert called["tray_only"] is False
        assert os.environ.get("DESKTOP_MODE") == "1"
    finally:
        os.environ.pop("DESKTOP_MODE", None)


def test_main_rejects_unknown_mode():
    import careerassistant.__main__ as entry

    assert entry.main(["bogus"]) == 2
