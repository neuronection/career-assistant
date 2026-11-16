"""Plan 212 S2.1 — the saved-posting closing-soon digest section and kind."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.engagement_model import NotificationKind
from app.services.postings.digest_service import (
    CLOSING_SOON_KIND,
    build_and_emit_digest,
)
from tests.conftest import _make_posting, _uid


async def _save(client, auth_headers, posting_id) -> None:
    response = await client.post(
        "/api/v1/postings/save",
        json={"posting_id": str(posting_id)},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text


async def test_closing_soon_kind_is_seeded(db, kinds):
    row = (
        (
            await db.execute(
                select(NotificationKind).where(NotificationKind.key == CLOSING_SOON_KIND)
            )
        )
        .scalars()
        .first()
    )
    assert row is not None
    assert row.default_channels == ["in_app", "desktop", "browser"]
    assert row.mutable is True


async def test_digest_alerts_only_saved_open_deadlines_in_window(
    client, auth_headers, profile_ready, seeded_catalog, db, source, kinds
):
    today = datetime.now(UTC).date()
    soon = await _make_posting(db, source, external_id="cs-soon", title="Closing intern")
    soon.application_deadline = today + timedelta(days=3)
    later = await _make_posting(db, source, external_id="cs-later", title="Closing later")
    later.application_deadline = today + timedelta(days=45)
    expired = await _make_posting(db, source, external_id="cs-expired", title="Closing expired")
    expired.application_deadline = today - timedelta(days=1)
    undated = await _make_posting(db, source, external_id="cs-undated", title="No deadline")
    unsaved = await _make_posting(db, source, external_id="cs-unsaved", title="Unsaved soon")
    unsaved.application_deadline = today + timedelta(days=2)
    await db.commit()
    for posting in (soon, later, expired, undated):
        await _save(client, auth_headers, posting.id)

    result = await build_and_emit_digest(db, _uid(auth_headers), now=datetime.now(UTC))
    assert result["closing_soon"] == 1
    assert result["closing_notified"] is True

    notifications = (await client.get("/api/v1/notifications", headers=auth_headers)).json()
    alerts = [n for n in notifications["items"] if n["kind"] == CLOSING_SOON_KIND]
    assert len(alerts) == 1
    assert alerts[0]["payload"]["count"] == 1
    assert alerts[0]["payload"]["posting_ids"] == [str(soon.id)]
    assert alerts[0]["payload"]["link"] == "/postings?saved=1"
    assert "Closing intern" in alerts[0]["body"]
    digest = next(n for n in notifications["items"] if n["kind"] == "digest_ready")
    assert "saved posting closes within 7 days" in digest["body"].lower()


async def test_digest_stays_quiet_without_a_deadline(
    client, auth_headers, profile_ready, seeded_catalog, db, source, kinds
):
    undated = await _make_posting(db, source, external_id="cs-quiet", title="No deadline")
    await db.commit()
    await _save(client, auth_headers, undated.id)

    result = await build_and_emit_digest(db, _uid(auth_headers), now=datetime.now(UTC))
    assert result["closing_soon"] == 0
    assert result["closing_notified"] is False
    notifications = (await client.get("/api/v1/notifications", headers=auth_headers)).json()
    assert not [n for n in notifications["items"] if n["kind"] == CLOSING_SOON_KIND]
