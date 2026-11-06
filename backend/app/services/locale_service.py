"""Locale resolution for the product surfaces (plan 121).

The UI locale is a per-user setting (`users.locale`); a NULL value means
"use the instance default" from `app_settings` `i18n.default_locale`, and
a missing setting falls back to the source locale. The same resolution
drives catalog label overlays so a user's UI and catalog never disagree.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings_model import AppSetting

if TYPE_CHECKING:
    from app.models.user_model import User

SOURCE_LOCALE = "en"
SUPPORTED_LOCALES: tuple[str, ...] = ("en", "de", "el")
LOCALE_NAMES: dict[str, str] = {"en": "English", "de": "German", "el": "Greek"}
DEFAULT_LOCALE_KEY = "i18n.default_locale"
_LOCALE_RE = re.compile(r"^[A-Za-z]{2}(-[A-Za-z]{2})?$")


def normalize_locale(value: str | None) -> str | None:
    """Return a supported short locale code, or None for an unusable value."""
    if not value:
        return None
    candidate = value.strip().split(",")[0].split(";")[0].strip()
    if not _LOCALE_RE.match(candidate):
        return None
    short = candidate.split("-")[0].lower()
    return short if short in SUPPORTED_LOCALES else None


async def instance_default_locale(db: AsyncSession) -> str:
    """The instance-wide UI locale (admin setting), source locale when unset."""
    row = (
        (await db.execute(select(AppSetting).where(AppSetting.key == DEFAULT_LOCALE_KEY)))
        .scalars()
        .first()
    )
    value = (row.value or {}).get("locale") if row is not None else None
    return normalize_locale(value) or SOURCE_LOCALE


async def set_instance_default_locale(db: AsyncSession, locale: str) -> str:
    """Persist the instance-wide default; returns the normalized locale."""
    normalized = normalize_locale(locale)
    if normalized is None:
        from app.core.errors import ValidationError

        raise ValidationError(f"Unsupported locale: {locale}")
    row = (
        (await db.execute(select(AppSetting).where(AppSetting.key == DEFAULT_LOCALE_KEY)))
        .scalars()
        .first()
    )
    if row is None:
        db.add(
            AppSetting(
                key=DEFAULT_LOCALE_KEY,
                value={"locale": normalized},
                description="Default UI locale for users without a personal choice",
            )
        )
    else:
        row.value = {"locale": normalized}
        db.add(row)
    await db.commit()
    return normalized


async def effective_locale(db: AsyncSession, user: User | None) -> str:
    """The locale a user sees: personal choice, then instance default, then en."""
    if user is not None:
        chosen = normalize_locale(user.locale)
        if chosen is not None:
            return chosen
    return await instance_default_locale(db)
