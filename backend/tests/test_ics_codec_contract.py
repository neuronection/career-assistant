"""Family ics_codec fixture wall (ADR-0059) — vendored contract test."""

import json
from pathlib import Path

import pytest

from app.services.postings.ics_codec import IcsCodecError, parse_ics

FIXTURES = Path(__file__).parent / "fixtures" / "ics-codec.fixtures.json"


def test_ics_codec_fixture_wall():
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]
    for case in cases:
        if "error" in case["expect"]:
            with pytest.raises(IcsCodecError, match=case["expect"]["error"]):
                parse_ics(case["ics"], max_bytes=case.get("maxBytes", 2_000_000))
            continue
        result = parse_ics(
            case["ics"],
            include_cancelled=case["includeCancelled"],
            default_timezone=case.get("defaultTimezone", "UTC"),
            max_events=case.get("maxEvents", 200),
            max_bytes=case.get("maxBytes", 2_000_000),
        )
        expected = case["expect"]
        assert [
            {
                "uid": event.uid,
                "summary": event.summary,
                "start": event.start.isoformat(),
                "allDay": event.all_day,
            }
            for event in result.events
        ] == expected.get("events", []), case["name"]
        assert result.warnings == expected.get("warnings", []), case["name"]


def test_ics_codec_rejects_non_calendar():
    try:
        parse_ics("not a calendar")
    except IcsCodecError as exc:
        assert "VCALENDAR" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected IcsCodecError")
