"""Engagement API schemas (Phase 24): searches, feed, notifications."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.enums import (
    FeedTokenKind,
    NotificationRuleKind,
    NotificationSeverity,
    NotificationStatus,
    SearchScope,
)
from app.schemas.job import JobOut
from app.schemas.matching import MatchInsightOut


class SearchRecordIn(BaseModel):
    scope: SearchScope
    query: str = Field(default="", max_length=300)
    filters: dict = Field(default_factory=dict)
    result_count: int = Field(default=0, ge=0)
    saved: bool = False
    name: str | None = Field(default=None, max_length=80)


class SearchUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    query: str | None = Field(default=None, max_length=300)
    filters: dict | None = None
    result_count: int | None = Field(default=None, ge=0)


class SearchOut(BaseModel):
    id: UUID
    scope: SearchScope
    query: str
    filters: dict
    result_count: int
    saved: bool
    name: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class FeedItemOut(BaseModel):
    job: JobOut
    fit_score: float
    insight: MatchInsightOut | None = None
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
    # Discretion: employed users keep pings inside a window.
    # Pre-36 the check runs at emit; moves it to dispatch.
    quiet_hours: dict | None = None

    @field_validator("family_keys", "muted_family_keys")
    @classmethod
    def _keys_are_slugs(cls, value: list[str]) -> list[str]:
        for key in value:
            if not key or len(key) > 80 or key.strip() != key:
                raise ValueError(f"invalid family key: {key!r}")
        return value

    @field_validator("quiet_hours")
    @classmethod
    def _quiet_window_shape(cls, value: dict | None) -> dict | None:
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


class NotificationPayloadOut(BaseModel):
    """Notification action payload (emitter-keyed, open-ended)."""

    model_config = {"extra": "allow"}

    job_id: str | None = None
    job_code: str | None = None
    family_key: str | None = None
    score: float | None = None
    link: str | None = None
    proposal_ids: list[str] = Field(default_factory=list)
    chat_session_id: str | None = None


class NotificationOut(BaseModel):
    id: UUID
    notification_id: UUID
    kind: str
    severity: NotificationSeverity
    status: NotificationStatus
    title: str
    body: str
    payload: NotificationPayloadOut
    source_ref: dict = Field(default_factory=dict)
    thread_key: str | None = None
    read_at: datetime | None = None
    dismissed_at: datetime | None = None
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
    """Global channel preferences (Phase 30 shape, matrix above)."""

    desktop_channel_enabled: bool = True
    quiet_hours: QuietHoursIn | None = None


class NotificationPreferencesOut(BaseModel):
    desktop_channel_enabled: bool
    quiet_hours: QuietHoursIn | None = None


class KindPrefOut(BaseModel):
    key: str
    label: str
    group: str
    severity: str
    manage_url: str | None = None
    mutable: bool
    default_channels: list[str]
    enabled: bool
    channels: list[str]
    overridden: bool = False


class PreferencesMatrixOut(BaseModel):
    """The full per-kind x per-channel matrix."""

    channels: list[str]
    quiet_hours: QuietHoursIn | None = None
    desktop_channel_enabled: bool = True
    kinds: list[KindPrefOut]


class KindPrefIn(BaseModel):
    enabled: bool | None = None
    channels: list[str] | None = Field(default=None, max_length=6)

    @field_validator("channels")
    @classmethod
    def _known_channels(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        allowed = {"in_app", "desktop", "browser", "email", "webhook"}
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
    user_agent: str | None = Field(default=None, max_length=300)


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
    link: str | None = Field(default=None, max_length=300)


class UnseenCountOut(BaseModel):
    unseen: int


class EmailChannelConfigIn(BaseModel):
    """Per-user email channel config; a changed address needs verification."""

    enabled: bool = True
    address: str | None = Field(default=None, max_length=320)
    digest_mode: bool = False


class EmailChannelConfigOut(BaseModel):
    enabled: bool
    address: str
    pending_address: str = ""
    digest_mode: bool = False
    verified: bool = False
    verified_at: datetime | None = None


class EmailVerifyIn(BaseModel):
    token: str = Field(min_length=16, max_length=200)


class EmailVerificationOut(BaseModel):
    sent: bool
    pending_address: str = ""


class ChannelTestOut(BaseModel):
    channel: str
    delivery_id: str
    status: str
    error: str | None = None


class DeliveryOut(BaseModel):
    """One channel dispatch row (the per-channel health strip)."""

    id: UUID
    channel: str
    status: str
    error: str | None = None
    kind: str | None = None
    created_at: datetime


class DeliveriesOut(BaseModel):
    items: list[DeliveryOut]


class WebhookChannelConfigIn(BaseModel):
    """Per-user webhook config; `***` keeps the sealed token slot."""

    enabled: bool = True
    url: str | None = Field(default=None, max_length=1000)
    template: str | None = Field(default=None, max_length=40)
    secret: str | None = Field(default=None, max_length=500)


class WebhookChannelConfigOut(BaseModel):
    enabled: bool
    url: str
    template: str
    secret_set: bool = False
    verified: bool = False
    verified_at: datetime | None = None


class EmailTransportIn(BaseModel):
    """Instance SMTP config (admin); a `***` password keeps the sealed slot."""

    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=255)
    from_address: str | None = Field(default=None, max_length=320)
    from_name: str | None = Field(default=None, max_length=120)
    starttls: bool | None = None
    use_ssl: bool | None = None
    password: str | None = Field(default=None, max_length=500)


class EmailTransportOut(BaseModel):
    host: str
    port: int
    username: str
    from_address: str
    from_name: str
    starttls: bool
    use_ssl: bool
    password_set: bool


class FeedTokenIn(BaseModel):
    """Mint a calendar/RSS token; an RSS token may scope to a saved search."""

    kind: FeedTokenKind
    scope: dict = Field(default_factory=dict)


class FeedTokenOut(BaseModel):
    id: UUID
    kind: FeedTokenKind
    scope: dict
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    rotated_from_id: UUID | None = None


class FeedTokenMintedOut(FeedTokenOut):
    token: str
