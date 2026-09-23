from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from pipeline.deadline_parser import DeadlineParseError, parse_deadline


TZ = ZoneInfo("Asia/Manila")
REFERENCE = datetime(2026, 9, 24, 8, 30, tzinfo=TZ)


def test_parse_iso_preserves_explicit_offset():
    assert parse_deadline("2026-09-27T10:00:00+00:00", now=REFERENCE).isoformat() == "2026-09-27T10:00:00+00:00"


def test_parse_tomorrow_at_time():
    parsed = parse_deadline("tomorrow at 9am", now=REFERENCE)
    assert parsed == datetime(2026, 9, 25, 9, 0, tzinfo=TZ)


def test_parse_time_first_tomorrow():
    parsed = parse_deadline("at 9am tomorrow", now=REFERENCE)
    assert parsed == datetime(2026, 9, 25, 9, 0, tzinfo=TZ)


def test_parse_relative_duration():
    parsed = parse_deadline("in 2 hours", now=REFERENCE)
    assert parsed == datetime(2026, 9, 24, 10, 30, tzinfo=TZ)


def test_parse_next_weekday_at_time():
    parsed = parse_deadline("Friday at 5pm", now=REFERENCE)
    assert parsed == datetime(2026, 9, 25, 17, 0, tzinfo=TZ)


def test_parse_next_keyword_for_same_weekday_moves_forward():
    parsed = parse_deadline("next Thursday at 9am", now=REFERENCE)
    assert parsed == datetime(2026, 10, 1, 9, 0, tzinfo=TZ)


def test_unparseable_deadline_raises():
    with pytest.raises(DeadlineParseError):
        parse_deadline("sometime when the moon is full", now=REFERENCE)
