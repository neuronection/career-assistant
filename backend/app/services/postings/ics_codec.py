"""Family ICS codec (ADR-0059).

A small, dependency-free RFC 5545 read codec for hosts that import one
calendar file (not a cloud account). It knows how to parse VEVENTs into a
normalized event shape with explicit warnings; it does **not** bind
accounts, talk to CalDAV/Google/Graph, reconcile or persist.

Canonical copy lives in the family standards (``contracts/ics_codec.py``)
and is vendored byte-identical into product hosts via
``scripts/sync-ics-codec.sh``. Edit the canonical copy only.

Decisions fixed by the contract:

* Windows/Outlook TZIDs are mapped to IANA; an unknown TZID skips the event
  with a warning instead of silently using UTC.
* A UTF-8 BOM is stripped; CRLF/LF and folded lines are accepted.
* ``METHOD:CANCEL`` and ``STATUS:CANCELLED`` are reported on the event;
  callers choose whether to import them.
* A recurrence (``RRULE``) is kept as one master event with a warning in
  v1 — this codec does not expand occurrences.
* A missing UID is accepted with a warning (file import is not a sync
  identity); ``MAX_EVENTS``/``MAX_BYTES`` bound the read.
* All-day events are returned as UTC-midnight datetimes with
  ``all_day=True``; timed events are timezone-aware UTC datetimes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

MAX_EVENTS = 200
MAX_BYTES = 2_000_000

WINDOWS_TZIDS = {
    "UTC": "UTC",
    "GMT Standard Time": "Europe/London",
    "W. Europe Standard Time": "Europe/Berlin",
    "Central Europe Standard Time": "Europe/Budapest",
    "Central European Standard Time": "Europe/Warsaw",
    "Romance Standard Time": "Europe/Paris",
    "E. Europe Standard Time": "Europe/Chisinau",
    "Eastern Standard Time": "America/New_York",
    "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver",
    "Pacific Standard Time": "America/Los_Angeles",
    "India Standard Time": "Asia/Kolkata",
    "Tokyo Standard Time": "Asia/Tokyo",
    "AUS Eastern Standard Time": "Australia/Sydney",
}

_LINE = re.compile(r"\r?\n")
_NON_WORD = re.compile(r"[^a-z0-9]+")


class IcsCodecError(ValueError):
    """Typed parse failure (bad container, oversized input)."""


@dataclass(frozen=True)
class IcsEvent:
    uid: str
    summary: str
    start: datetime
    end: datetime | None
    all_day: bool
    description: str = ""
    location: str = ""
    status: str = ""
    cancelled: bool = False
    sequence: int | None = None


@dataclass
class IcsParseResult:
    events: list[IcsEvent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _unfold(text: str) -> list[str]:
    text = text.lstrip("\ufeff")
    lines: list[str] = []
    for raw in _LINE.split(text):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _split_property(line: str) -> tuple[str, dict[str, str], str] | None:
    if ":" not in line:
        return None
    left, value = line.split(":", 1)
    parts = left.split(";")
    name = parts[0].strip().upper()
    params: dict[str, str] = {}
    for raw in parts[1:]:
        if "=" in raw:
            key, val = raw.split("=", 1)
            params[key.strip().upper()] = val.strip().strip('"')
    return name, params, value


def _parse_when(
    value: str, params: dict[str, str], default_timezone: str = "UTC"
) -> tuple[datetime, bool]:
    raw = value.strip()
    all_day = params.get("VALUE", "").upper() == "DATE" or (len(raw) == 8 and raw.isdigit())
    if all_day:
        day = datetime.strptime(raw[:8], "%Y%m%d")
        return day.replace(tzinfo=UTC), True
    if raw.endswith("Z"):
        return datetime.strptime(raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=UTC), False
    parsed = datetime.strptime(raw[:15], "%Y%m%dT%H%M%S")
    tzid = params.get("TZID")
    if tzid:
        zone_name = WINDOWS_TZIDS.get(tzid, tzid)
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(zone_name))
        except Exception as exc:
            raise IcsCodecError(f"unknown TZID: {tzid}") from exc
    else:
        parsed = parsed.replace(tzinfo=ZoneInfo(default_timezone))
    return parsed.astimezone(UTC), False


def parse_ics(
    text: str,
    *,
    include_cancelled: bool = False,
    default_timezone: str = "UTC",
    max_events: int = MAX_EVENTS,
    max_bytes: int = MAX_BYTES,
) -> IcsParseResult:
    raw = text or ""
    if len(raw.encode("utf-8")) > max_bytes:
        raise IcsCodecError("ICS file is too large")
    lines = _unfold(raw)
    if not any(line.strip().upper() == "BEGIN:VCALENDAR" for line in lines):
        raise IcsCodecError("Not an ICS calendar (no VCALENDAR)")

    result = IcsParseResult()
    method_cancel = any(line.strip().upper() == "METHOD:CANCEL" for line in lines)
    current: dict[str, tuple[str, dict[str, str]]] | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        upper = stripped.upper()
        if upper == "BEGIN:VEVENT":
            current = {}
            continue
        if upper == "END:VEVENT":
            if current is None:
                continue
            event = _event_from(current, index, result.warnings, method_cancel, default_timezone)
            if event is not None and (include_cancelled or not event.cancelled):
                if len(result.events) >= max_events:
                    result.warnings.append(f"only the first {max_events} events were read")
                    break
                result.events.append(event)
            current = None
            continue
        if current is None:
            continue
        prop = _split_property(stripped)
        if prop is None:
            continue
        name, params, value = prop
        if name in {
            "UID",
            "SUMMARY",
            "DESCRIPTION",
            "LOCATION",
            "STATUS",
            "DTSTART",
            "DTEND",
            "RRULE",
            "SEQUENCE",
            "METHOD",
        }:
            current[name] = (value, params)
    return result


def _event_from(
    raw: dict[str, tuple[str, dict[str, str]]],
    index: int,
    warnings: list[str],
    method_cancel: bool,
    default_timezone: str,
) -> IcsEvent | None:
    start_prop = raw.get("DTSTART")
    if start_prop is None:
        warnings.append(f"VEVENT at line {index} has no DTSTART and was skipped")
        return None
    try:
        start, all_day = _parse_when(*start_prop, default_timezone)
    except (ValueError, IcsCodecError) as exc:
        warnings.append(f"VEVENT at line {index} has an unreadable DTSTART: {exc}")
        return None
    end: datetime | None = None
    if "DTEND" in raw:
        try:
            end, _ = _parse_when(*raw["DTEND"], default_timezone)
        except (ValueError, IcsCodecError):
            warnings.append(f"VEVENT at line {index} has an unreadable DTEND; ignored")
    uid = raw.get("UID", ("", {}))[0].strip()[:300]
    if not uid:
        warnings.append(f"VEVENT at line {index} has no UID; accepted as a file import")
    if "RRULE" in raw:
        warnings.append(f"VEVENT at line {index} has a recurrence rule; only the master was read")
    status = raw.get("STATUS", ("", {}))[0].strip().upper()[:40]
    event_method = raw.get("METHOD", ("", {}))[0].strip().upper()
    cancelled = method_cancel or event_method == "CANCEL" or status == "CANCELLED"
    sequence_raw = raw.get("SEQUENCE", ("", {}))[0].strip()
    sequence = int(sequence_raw) if sequence_raw.isdigit() else None
    return IcsEvent(
        uid=uid,
        summary=raw.get("SUMMARY", ("", {}))[0].strip()[:400],
        start=start,
        end=end,
        all_day=all_day,
        description=raw.get("DESCRIPTION", ("", {}))[0][:4000],
        location=raw.get("LOCATION", ("", {}))[0][:500],
        status=status,
        cancelled=cancelled,
        sequence=sequence,
    )


def normalize_text(value: str) -> str:
    """Normalize summary/location text for host-side matching."""
    return " ".join(_NON_WORD.sub(" ", (value or "").lower()).split())
