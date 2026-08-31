"""Scheduler trigger registry (Phase 29) — same plugin pattern as the
connector SDK (26). Each trigger type is a small class: `validate(params)`
→ pydantic model, `next_after(now, params)` → next due datetime (aware,
UTC-normalized). Third parties register via the
`career_assistant.scheduler_triggers` entry-point group; the contract kit
(ContractTriggerTests) verifies the promises the runner depends on."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from importlib import metadata
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from app.core.errors import ValidationError

ENTRY_POINT_GROUP = "career_assistant.scheduler_triggers"

HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour, minute = value.split(":")
    return int(hour), int(minute)


class IntervalTrigger:
    """Every N minutes, with optional jitter to spread system syncs."""

    key = "interval"

    class Params(BaseModel):
        every_minutes: int = Field(ge=1, le=60 * 24 * 365)
        jitter_minutes: int = Field(default=0, ge=0, le=60 * 24)

    @classmethod
    def validate(cls, params: dict) -> BaseModel:
        return cls.Params.model_validate(params)

    @classmethod
    def next_after(cls, now: datetime, params: dict, *, rnd=random.uniform) -> datetime:
        parsed = cls.Params.model_validate(params)
        jitter = rnd(0, parsed.jitter_minutes * 60) if parsed.jitter_minutes else 0.0
        return now + timedelta(minutes=parsed.every_minutes, seconds=jitter)


class DailyAtTrigger:
    """Daily at HH:MM in a named IANA timezone (plan 42 time policy)."""

    key = "daily_at"

    class Params(BaseModel):
        time: str = Field(pattern=HHMM)
        timezone: str = "UTC"

    @classmethod
    def validate(cls, params: dict) -> BaseModel:
        parsed = cls.Params.model_validate(params)
        try:
            ZoneInfo(parsed.timezone)
        except Exception as exc:  # noqa: BLE001 — invalid tz names vary
            raise ValidationError(f"Unknown timezone: {parsed.timezone}") from exc
        return parsed

    @classmethod
    def next_after(cls, now: datetime, params: dict, *, rnd=random.uniform) -> datetime:
        parsed = cls.Params.model_validate(params)
        hour, minute = _parse_hhmm(parsed.time)
        tz = ZoneInfo(parsed.timezone)
        local = now.astimezone(tz)
        candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= local:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)


class WeeklyTrigger:
    """Weekly on weekday (0=Monday … 6=Sunday) at HH:MM in a timezone."""

    key = "weekly"

    class Params(BaseModel):
        weekday: int = Field(ge=0, le=6)
        time: str = Field(pattern=HHMM)
        timezone: str = "UTC"

    @classmethod
    def validate(cls, params: dict) -> BaseModel:
        parsed = cls.Params.model_validate(params)
        try:
            ZoneInfo(parsed.timezone)
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(f"Unknown timezone: {parsed.timezone}") from exc
        return parsed

    @classmethod
    def next_after(cls, now: datetime, params: dict, *, rnd=random.uniform) -> datetime:
        parsed = cls.Params.model_validate(params)
        hour, minute = _parse_hhmm(parsed.time)
        tz = ZoneInfo(parsed.timezone)
        local = now.astimezone(tz)
        candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = (parsed.weekday - candidate.weekday()) % 7
        candidate += timedelta(days=days_ahead)
        if candidate <= local:
            candidate += timedelta(days=7)
        return candidate.astimezone(timezone.utc)


class CronTrigger:
    """5-field cron (minute hour dom month dow), no external dependency.

    Supports *, lists (a,b), ranges (a-b) and steps (star-slash-n)."""

    key = "cron"

    class Params(BaseModel):
        expr: str = Field(min_length=9, max_length=100)

        @field_validator("expr")
        @classmethod
        def _parsable(cls, value: str) -> str:
            cls.parse_expr(value)  # raises ValidationError when malformed
            return value

        @staticmethod
        def parse_expr(expr: str) -> list[set[int]]:
            fields = expr.split()
            if len(fields) != 5:
                raise ValidationError("cron expr must have 5 fields")
            ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
            parsed: list[set[int]] = []
            for field, (low, high) in zip(fields, ranges):
                values: set[int] = set()
                for part in field.split(","):
                    step = 1
                    body = part
                    if "/" in part:
                        body, step_str = part.split("/", 1)
                        if not step_str.isdigit() or int(step_str) < 1:
                            raise ValidationError(f"bad cron step: {part}")
                        step = int(step_str)
                    if body == "*":
                        values.update(range(low, high + 1, step))
                    elif "-" in body:
                        bounds = body.split("-")
                        if not all(b.isdigit() for b in bounds) or len(bounds) != 2:
                            raise ValidationError(f"bad cron range: {part}")
                        a, b = int(bounds[0]), int(bounds[1])
                        if a < low or b > high or a > b:
                            raise ValidationError(f"cron range out of bounds: {part}")
                        values.update(range(a, b + 1, step))
                    elif body.isdigit():
                        number = int(body)
                        if number < low or number > high:
                            raise ValidationError(f"cron value out of bounds: {part}")
                        values.add(number)
                    else:
                        raise ValidationError(f"bad cron field: {part}")
                if not values:
                    raise ValidationError(f"empty cron field: {field}")
                parsed.append(values)
            return parsed

    @classmethod
    def validate(cls, params: dict) -> BaseModel:
        return cls.Params.model_validate(params)

    @classmethod
    def next_after(cls, now: datetime, params: dict, *, rnd=random.uniform) -> datetime:
        parsed = cls.Params.model_validate(params)
        minutes, hours, doms, months, dows = cls.Params.parse_expr(parsed.expr)
        candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        # dom/dow: standard cron ORs them when both are restricted.
        dom_restricted = parsed.expr.split()[2] != "*"
        dow_restricted = parsed.expr.split()[4] != "*"
        limit = candidate + timedelta(days=366 * 2)
        while candidate < limit:
            if candidate.month not in months:
                # jump to the first day of the next allowed month
                month = candidate.month
                while month not in months:
                    month += 1
                    if month > 12:
                        month = 1
                candidate = candidate.replace(
                    year=candidate.year + (1 if month <= candidate.month else 0),
                    month=month,
                    day=1,
                    hour=0,
                    minute=0,
                )
                continue
            day_ok = candidate.day in doms
            dow_ok = candidate.weekday() in dows
            if dom_restricted and dow_restricted:
                date_ok = day_ok or dow_ok
            elif dom_restricted:
                date_ok = day_ok
            elif dow_restricted:
                date_ok = dow_ok
            else:
                date_ok = True
            if not date_ok:
                candidate = (candidate + timedelta(days=1)).replace(hour=0, minute=0)
                continue
            if candidate.hour not in hours:
                next_hour = (
                    min(h for h in hours if h > candidate.hour)
                    if any(h > candidate.hour for h in hours)
                    else None
                )
                if next_hour is None:
                    candidate = (candidate + timedelta(days=1)).replace(
                        hour=0, minute=0
                    )
                else:
                    candidate = candidate.replace(hour=next_hour, minute=0)
                continue
            if candidate.minute not in minutes:
                next_minute = (
                    min(m for m in minutes if m > candidate.minute)
                    if any(m > candidate.minute for m in minutes)
                    else None
                )
                if next_minute is None:
                    candidate = (candidate + timedelta(hours=1)).replace(minute=0)
                else:
                    candidate = candidate.replace(minute=next_minute)
                continue
            return candidate.astimezone(timezone.utc)
        raise ValidationError("cron expr never matches (horizon exceeded)")


class BootStaleTrigger:
    """Fires when the last run is older than N minutes — replaces the
    ad-hoc on-boot staleness checks scattered across earlier plans."""

    key = "boot_stale"

    class Params(BaseModel):
        older_than_minutes: int = Field(ge=1, le=60 * 24 * 365)

    @classmethod
    def validate(cls, params: dict) -> BaseModel:
        return cls.Params.model_validate(params)

    @classmethod
    def next_after(cls, now: datetime, params: dict, *, rnd=random.uniform) -> datetime:
        parsed = cls.Params.model_validate(params)
        return now + timedelta(minutes=parsed.older_than_minutes)


TRIGGERS: dict[str, type] = {
    IntervalTrigger.key: IntervalTrigger,
    DailyAtTrigger.key: DailyAtTrigger,
    WeeklyTrigger.key: WeeklyTrigger,
    CronTrigger.key: CronTrigger,
    BootStaleTrigger.key: BootStaleTrigger,
}

_plugins_loaded = False


def _load_plugins() -> None:
    global _plugins_loaded
    if _plugins_loaded:
        return
    _plugins_loaded = True
    try:
        eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:
        return
    for ep in eps:
        try:
            trigger = ep.load()
        except Exception:  # noqa: BLE001 — one bad plugin never breaks boot
            continue
        if hasattr(trigger, "key") and hasattr(trigger, "next_after"):
            TRIGGERS.setdefault(trigger.key, trigger)


def reset_registry() -> None:
    global _plugins_loaded
    for key in list(TRIGGERS):
        if key not in {
            IntervalTrigger.key,
            DailyAtTrigger.key,
            WeeklyTrigger.key,
            CronTrigger.key,
            BootStaleTrigger.key,
        }:
            del TRIGGERS[key]
    _plugins_loaded = False


def register_trigger(trigger_cls) -> None:
    TRIGGERS[trigger_cls.key] = trigger_cls


def resolve_trigger(trigger: dict):
    """`trigger` JSONB: {"type": "interval", "params": {...}} → (cls, params_model)."""
    if not isinstance(trigger, dict) or "type" not in trigger:
        raise ValidationError("trigger must be {type, params}")
    _load_plugins()
    trigger_cls = TRIGGERS.get(trigger["type"])
    if trigger_cls is None:
        raise ValidationError(f"Unknown trigger type: {trigger['type']}")
    params = trigger.get("params") or {}
    return trigger_cls, trigger_cls.validate(params)


def next_after(trigger: dict, now: datetime, *, rnd=random.uniform) -> datetime:
    trigger_cls, params = resolve_trigger(trigger)
    return trigger_cls.next_after(now, params.model_dump(), rnd=rnd)
