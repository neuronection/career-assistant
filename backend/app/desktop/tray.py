"""System tray (pystray, desktop requirements only): icon states, menu,
background-mode wiring.

The pure pieces — icon state math, badge label, the menu model and
`TrayActions` (service-backed, same layer the API endpoints use) — are
importable without pystray so tests cover them everywhere. The pystray
`Icon` adapter degrades: missing AppIndicator / no pystray ⇒ no tray,
the app keeps running (never crashes over a missing systray host).
"""

import logging
from dataclasses import dataclass
from typing import Callable, Optional
from uuid import UUID

from sqlalchemy import select

logger = logging.getLogger(__name__)

BADGE_CAP = 9


@dataclass
class TrayStatus:
    unread: int = 0
    sync_running: bool = False


def icon_state(status: TrayStatus) -> str:
    """idle · sync · unread — sync wins (animation draws the eye)."""
    if status.sync_running:
        return "sync"
    if status.unread > 0:
        return "unread"
    return "idle"


def badge_label(unread: int) -> Optional[str]:
    """Badge count math: 1–9 numeric, 10+ capped, 0/None ⇒ no badge."""
    if unread <= 0:
        return None
    return str(unread) if unread <= BADGE_CAP else f"{BADGE_CAP}+"


def build_menu_model(
    *,
    saved_searches: list[dict],
    notifications: list[dict],
    unread: int,
    close_to_tray: bool,
    autostart: bool,
    has_tray: bool = True,
) -> list[dict]:
    """The plan-30 menu: Open · Sync now · Saved searches ▸ ·
    Notifications ▸ (last 5, mark read) · Quit (+ pref toggles)."""
    menu: list[dict] = [{"id": "open", "label": "Open Career Assistant"}]
    if has_tray:
        menu.append({"id": "sync_now", "label": "Sync now"})
        menu.append(
            {
                "id": "saved_searches",
                "label": "Saved searches",
                "items": [
                    submenu
                    for item in saved_searches
                    for submenu in (
                        {
                            "id": f"search:{item['schedule_id']}:run",
                            "label": f"Run now — {item['label']}",
                        },
                        {
                            "id": f"search:{item['schedule_id']}:toggle",
                            "label": (
                                f"{'Disable' if item['enabled'] else 'Enable'}"
                                f" {item['label']}"
                            ),
                        },
                    )
                ]
                or [{"id": "noop", "label": "No saved searches", "enabled": False}],
            }
        )
    notifications_label = (
        f"Notifications ({badge_label(unread)})" if unread else "Notifications"
    )
    menu.append(
        {
            "id": "notifications",
            "label": notifications_label,
            "items": (
                [
                    {
                        "id": f"notification:{item['id']}",
                        "label": item["title"][:60],
                    }
                    for item in notifications
                ]
                + [{"id": "notifications:mark_read", "label": "Mark all read"}]
            ),
        }
    )
    menu.append(
        {
            "id": "toggle_close_to_tray",
            "label": "Close to tray",
            "checked": close_to_tray,
        }
    )
    menu.append(
        {"id": "toggle_autostart", "label": "Start on login", "checked": autostart}
    )
    menu.append({"id": "quit", "label": "Quit"})
    return menu


class TrayActions:
    """Menu behaviour over the same service layer the web UI endpoints use.

    The tray is the desktop *owner's* surface: notification scoping is the
    admin accounts (a shared machine's other users keep their inbox
    private in-app).
    """

    def __init__(self, session_factory, bridge) -> None:
        self._session_factory = session_factory
        self._bridge = bridge

    async def open(self) -> None:
        self._bridge.show_and_focus()

    async def owner_ids(self) -> list[UUID]:
        from app.models.user_model import User

        async with self._session_factory() as db:
            rows = await db.execute(
                select(User.id).where(User.is_admin.is_(True)).limit(5)
            )
            return list(rows.scalars().all())

    async def sync_now(self) -> int:
        """Run every enabled system source-sync schedule now."""
        from app.models.enums import ScheduleKind
        from app.services.scheduler.runner import SchedulerService

        fired = 0
        async with self._session_factory() as db:
            service = SchedulerService(db)
            for schedule in await service.list_schedules(None):
                if schedule.kind == ScheduleKind.SYSTEM_SOURCE_SYNC.value:
                    try:
                        await service.run_now(schedule.id)
                        fired += 1
                    except Exception:  # noqa: BLE001 — degrade per schedule
                        logger.warning("Tray sync-now failed", exc_info=True)
        return fired

    async def saved_searches(self) -> list[dict]:
        from sqlalchemy import select

        from app.models.engagement_model import SearchHistory
        from app.services.scheduler.runner import SchedulerService

        async with self._session_factory() as db:
            service = SchedulerService(db)
            items: list[dict] = []
            for owner in await self.owner_ids():
                for schedule in await service.list_schedules(owner):
                    if schedule.kind != "user_saved_search":
                        continue
                    search_id = schedule.payload.get("search_id", "")
                    query = None
                    if search_id:
                        row = await db.execute(
                            select(SearchHistory.query).where(
                                SearchHistory.id == UUID(search_id)
                            )
                        )
                        query = row.scalars().first()
                    items.append(
                        {
                            "schedule_id": str(schedule.id),
                            "label": query or search_id or "search",
                            "enabled": schedule.enabled,
                        }
                    )
            return items

    async def run_saved_search(self, schedule_id: str) -> None:
        from app.services.scheduler.runner import SchedulerService

        async with self._session_factory() as db:
            await SchedulerService(db).run_now(UUID(schedule_id))

    async def toggle_saved_search(self, schedule_id: str, enabled: bool) -> None:
        from app.services.scheduler.runner import SchedulerService

        async with self._session_factory() as db:
            await SchedulerService(db).set_enabled(UUID(schedule_id), enabled)

    async def notifications(self, limit: int = 5) -> tuple[list[dict], int]:
        from app.services.engagement_service import EngagementService

        items: list[dict] = []
        unread = 0
        async with self._session_factory() as db:
            service = EngagementService(db)
            for owner in await self.owner_ids():
                result = await service.list_notifications(owner, limit=limit)
                for row in result["items"][:limit]:
                    items.append({"id": str(row["id"]), "title": row["title"]})
                unread += result["unread_count"]
        items.sort(key=lambda item: item["title"])
        return items[:limit], unread

    async def mark_all_read(self) -> int:
        from app.services.engagement_service import EngagementService

        marked = 0
        async with self._session_factory() as db:
            service = EngagementService(db)
            for owner in await self.owner_ids():
                marked += await service.mark_read(owner, [])
        return marked

    async def tray_status(self) -> TrayStatus:
        from sqlalchemy import text as sa_text

        unread = 0
        sync_running = False
        async with self._session_factory() as db:
            owners = await self.owner_ids()
            if owners:
                from app.models.engagement_model import NotificationRecipient

                rows = await db.execute(
                    select(NotificationRecipient.id).where(
                        NotificationRecipient.user_id.in_(owners),
                        NotificationRecipient.status == "unread",
                    )
                )
                unread = len(rows.scalars().all())
            jobs = await db.execute(
                sa_text(
                    "SELECT COUNT(*) FROM background_jobs "
                    "WHERE status = 'running' AND job_type = 'posting_sync'"
                )
            )
            sync_running = bool((jobs.scalar_one_or_none() or 0) > 0)
        return TrayStatus(unread=unread, sync_running=sync_running)


class TrayIcon:
    """pystray adapter; constructed only when pystray imports cleanly.

    The menu is (re)built from `build_menu_model` on every status poll so
    labels (badge counts, enabled toggles) track reality.
    """

    POLL_SECONDS = 5

    def __init__(
        self,
        actions: TrayActions,
        settings,
        data_dir,
        on_quit: Callable[[], None],
    ) -> None:
        import pystray

        self._pystray = pystray
        self._actions = actions
        self._settings = settings
        self._data_dir = data_dir
        self._on_quit = on_quit
        self._icon = None
        self._status = TrayStatus()
        self._snapshot_data: dict = {}

    def start(self) -> None:
        self._icon = self._pystray.Icon(
            "career-assistant",
            self._render(self._status),
            "Career Assistant",
            menu=self._build_menu(),
        )
        self._icon.run_detached()

    def poll(self) -> None:
        """Refresh badge/state + menu from the services (tray thread)."""
        import asyncio

        status = asyncio.run(self._actions.tray_status())
        snapshot = asyncio.run(self._snapshot(status))
        self._snapshot_data = snapshot
        self._status = status
        if self._icon is not None:
            try:
                self._icon.icon = self._render(status)
                self._icon.title = "Career Assistant — " + (
                    "syncing" if status.sync_running else "idle"
                )
                self._icon.menu = self._build_menu()
            except Exception:  # noqa: BLE001 — icon refresh is cosmetic
                logger.debug("Tray refresh failed", exc_info=True)

    async def _snapshot(self, status: TrayStatus) -> dict:
        return {
            "saved_searches": await self._actions.saved_searches(),
            "notifications": (await self._actions.notifications())[0],
            "unread": status.unread,
        }

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:  # noqa: BLE001 — degrade
                logger.debug("Tray stop failed", exc_info=True)
            self._icon = None

    def _build_menu(self):
        pystray = self._pystray
        snap = self._snapshot_data
        model = build_menu_model(
            saved_searches=snap.get("saved_searches", []),
            notifications=snap.get("notifications", []),
            unread=self._status.unread,
            close_to_tray=self._settings.close_to_tray is True,
            autostart=self._settings.autostart,
        )

        def entry(item: dict):
            if item.get("items"):
                # pystray has no Submenu class: a Menu used as the action
                # *is* the submenu.
                return pystray.MenuItem(
                    item["label"],
                    pystray.Menu(*[entry(child) for child in item["items"]]),
                )

            def action(_icon=None, _item=None):
                self._handle(item["id"])

            checked = item.get("checked")
            return pystray.MenuItem(
                item["label"],
                action,
                checked=(lambda _icon=None, _item=None, v=bool(checked): v)
                if "checked" in item
                else None,
                radio=False,
                default="checked" in item,
            )

        return pystray.Menu(*[entry(item) for item in model])

    def _handle(self, menu_id: str) -> None:
        import asyncio
        import threading

        def fire(coro) -> None:
            threading.Thread(target=lambda: asyncio.run(coro), daemon=True).start()

        if menu_id in ("open", ""):
            fire(self._actions.open())
        elif menu_id == "sync_now":
            fire(self._actions.sync_now())
        elif menu_id == "notifications:mark_read":
            fire(self._actions.mark_all_read())
        elif menu_id.startswith("notification:"):
            fire(self._actions.open())
        elif menu_id.startswith("search:"):
            _, schedule_id, verb = menu_id.split(":", 2)
            for item in self._snapshot_data.get("saved_searches", []):
                if item["schedule_id"] == schedule_id:
                    if verb == "run":
                        fire(self._actions.run_saved_search(schedule_id))
                    else:
                        fire(
                            self._actions.toggle_saved_search(
                                schedule_id, not item["enabled"]
                            )
                        )
                    break
            else:
                fire(self._actions.open())
        elif menu_id == "toggle_close_to_tray":
            self._settings.close_to_tray = self._settings.close_to_tray is not True
            self._settings.save(self._data_dir)
        elif menu_id == "toggle_autostart":
            from app.desktop import autostart

            self._settings.autostart = not self._settings.autostart
            autostart.set_autostart(self._settings.autostart)
            self._settings.save(self._data_dir)
        elif menu_id == "quit":
            self._on_quit()

    @staticmethod
    def _render(status: TrayStatus):
        from PIL import Image, ImageDraw

        state = icon_state(status)
        colors = {
            "idle": (100, 116, 139),
            "sync": (59, 130, 246),
            "unread": (244, 63, 94),
        }
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((8, 8, 56, 56), fill=colors[state])
        label = badge_label(status.unread)
        if label:
            draw.text((22, 22), label, fill="white")
        return image
