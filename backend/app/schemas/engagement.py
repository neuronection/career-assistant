"""Engagement API schemas (Phase 24): searches, feed, notifications."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.enums import NotificationRuleKind, SearchScope
from app.schemas.job import JobOut
from app.schemas.matching import MatchInsightOut


class SearchRecordIn(BaseModel):
    scope: SearchScope
    query: str = Field(default="", max_length=300)
    filters: dict = Field(default_factory=dict)
    result_count: int = Field(default=0, ge=0)


class SearchOut(BaseModel):
    id: UUID
    scope: SearchScope
    query: str
    filters: dict
    result_count: int
    saved: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class FeedItemOut(BaseModel):
    job: JobOut
    fit_score: float
    insight: Optional[MatchInsightOut] = None
    seen: bool = False
    saved: bool = False
    user_notes: str = ""
    exploration: bool = False


class FeedOut(BaseModel):
    items: list[FeedItemOut]
    total: int
    unseen: int


class SeenIn(BaseModel):
    job_ids: list[UUID] = Field(min_length=1, max_length=200)


class SaveIn(BaseModel):
    job_id: UUID
    saved: bool = True


class HideIn(BaseModel):
    job_id: UUID
    hidden: bool = True


class RuleParams(BaseModel):
    min_fit: float = Field(default=7.0, ge=0, le=10)
    family_keys: list[str] = Field(default_factory=list, max_length=30)
    muted_family_keys: list[str] = Field(default_factory=list, max_length=30)
    max_per_day: int = Field(default=5, ge=1, le=50)
    # Discretion (plan 28): employed users keep pings inside a window.
    # Pre-36 the check runs at emit; plan 36 moves it to dispatch.
    quiet_hours: Optional[dict] = None

    @field_validator("family_keys", "muted_family_keys")
    @classmethod
    def _keys_are_slugs(cls, value: list[str]) -> list[str]:
        for key in value:
            if not key or len(key) > 80 or key.strip() != key:
                raise ValueError(f"invalid family key: {key!r}")
        return value

    @field_validator("quiet_hours")
    @classmethod
    def _quiet_window_shape(cls, value: Optional[dict]) -> Optional[dict]:
        if value is None:
            return None
        start, end = value.get("start"), value.get("end")
        import re

        pattern = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
        if not (isinstance(start, str) and isinstance(end, str)):
            raise ValueError("quiet_hours needs start/end HH:MM strings")
        if not (pattern.match(start) and pattern.match(end)):
            raise ValueError("quiet_hours must be HH:MM strings")
        return {"start": start, "end": end}


class RuleIn(BaseModel):
    kind: NotificationRuleKind
    params: RuleParams = Field(default_factory=RuleParams)
    enabled: bool = True


class RuleOut(BaseModel):
    kind: NotificationRuleKind
    params: RuleParams
    enabled: bool
    is_default: bool = False


class RulesOut(BaseModel):
    items: list[RuleOut]


class NotificationOut(BaseModel):
    id: UUID
    notification_id: UUID
    kind: str
    severity: str
    status: str
    title: str
    body: str
    payload: dict
    source_ref: dict = Field(default_factory=dict)
    thread_key: Optional[str] = None
    read_at: Optional[datetime] = None
    dismissed_at: Optional[datetime] = None
    created_at: datetime


class NotificationsOut(BaseModel):
    items: list[NotificationOut]
    unread_count: int


class ThreadItemOut(NotificationOut):
    pass


class ThreadOut(BaseModel):
    thread_key: str
    kind: str
    severity: str
    title: str
    payload: dict
    source_ref: dict
    unread_count: int
    items: list[ThreadItemOut]
    created_at: datetime


class ThreadsOut(BaseModel):
    threads: list[ThreadOut]
    unread_count: int


class ReadIn(BaseModel):
    ids: list[UUID] = Field(default_factory=list, max_length=200)


class QuietHoursIn(BaseModel):
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, value: str) -> str:
        import re

        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", value or ""):
            raise ValueError("quiet hours must be HH:MM strings")
        return value


class NotificationPreferencesIn(BaseModel):
    """Global channel preferences (Phase 30 shape, plan 36 matrix above)."""

    desktop_channel_enabled: bool = True
    quiet_hours: Optional[QuietHoursIn] = None


class NotificationPreferencesOut(BaseModel):
    desktop_channel_enabled: bool
    quiet_hours: Optional[QuietHoursIn] = None


class KindPrefOut(BaseModel):
    key: str
    label: str
    group: str
    severity: str
    manage_url: Optional[str] = None
    mutable: bool
    default_channels: list[str]
    enabled: bool
    channels: list[str]
    overridden: bool = False


class PreferencesMatrixOut(BaseModel):
    """The full per-kind × per-channel matrix (plan 36 preferences)."""

    channels: list[str]
    quiet_hours: Optional[QuietHoursIn] = None
    desktop_channel_enabled: bool = True
    kinds: list[KindPrefOut]


class KindPrefIn(BaseModel):
    enabled: Optional[bool] = None
    channels: Optional[list[str]] = Field(default=None, max_length=6)

    @field_validator("channels")
    @classmethod
    def _known_channels(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        allowed = {"in_app", "desktop", "browser"}
        unknown = [c for c in value if c not in allowed]
        if unknown:
            raise ValueError(f"unknown channels: {', '.join(unknown)}")
        return value


class KindPrefUpdateOut(BaseModel):
    """Compact response for a single kind preference update."""

    key: str
    enabled: bool
    channels: list[str]


class SubscriptionIn(BaseModel):
    """A browser PushSubscription (endpoint + keys) for VAPID delivery."""

    endpoint: str = Field(min_length=1, max_length=1000)
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=200)
    device_id: str = Field(default="web", max_length=120)
    user_agent: Optional[str] = Field(default=None, max_length=300)


class SubscriptionOut(BaseModel):
    device_id: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class VapidKeyOut(BaseModel):
    public_key: str


class BroadcastIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=2000)
    link: Optional[str] = Field(default=None, max_length=300)


class UnseenCountOut(BaseModel):
    unseen: int
