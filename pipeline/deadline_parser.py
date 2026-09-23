"""Deterministic parsing for natural-language task deadlines."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Final

from dateutil import parser as date_parser


class DeadlineParseError(ValueError):
    """Raised when a deadline string cannot be interpreted safely."""


_WEEKDAYS: Final[dict[str, int]] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_TIME_ONLY_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:at\s+)?(?P<time>\d{1,2}(?::\d{2})?\s*(?:am|pm))$",
    re.IGNORECASE,
)
_RELATIVE_RE: Final[re.Pattern[str]] = re.compile(
    r"^in\s+(?P<amount>\d+)\s+(?P<unit>minute|minutes|hour|hours|day|days|week|weeks)$",
    re.IGNORECASE,
)
_WEEKDAY_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:(?P<next>next)\s+)?(?P<weekday>monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"(?:\s+(?:at\s+)?(?P<time>.+))?$",
    re.IGNORECASE,
)
_DAY_ANCHOR_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<anchor>today|tomorrow|day\s+after\s+tomorrow|yesterday)"
    r"(?:\s+at\s+(?P<time>.+))?$",
    re.IGNORECASE,
)
_TIME_FIRST_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:at\s+)?(?P<time>\d{1,2}(?::\d{2})?\s*(?:am|pm))\s+"
    r"(?P<anchor>today|tomorrow|day\s+after\s+tomorrow|yesterday)$",
    re.IGNORECASE,
)


def parse_deadline(value: object, *, now: datetime | None = None) -> datetime:
    """Parse an ISO or common relative/natural-language deadline.

    Relative phrases are interpreted in the timezone of ``now``. When ``now`` is
    omitted, the host's current local timezone is captured as an aware datetime.
    Explicit timezone offsets in ISO input are preserved.
    """
    if isinstance(value, datetime):
        return _ensure_aware(value, now)
    if not isinstance(value, str) or not value.strip():
        raise DeadlineParseError("deadline must be a non-empty string or datetime")

    reference = _ensure_aware(now or datetime.now().astimezone(), now)
    text = " ".join(value.strip().split())

    iso = _parse_iso(text, reference)
    if iso is not None:
        return iso

    relative = _RELATIVE_RE.fullmatch(text)
    if relative:
        amount = int(relative.group("amount"))
        unit = relative.group("unit").lower()
        delta = {
            "minute": timedelta(minutes=amount),
            "minutes": timedelta(minutes=amount),
            "hour": timedelta(hours=amount),
            "hours": timedelta(hours=amount),
            "day": timedelta(days=amount),
            "days": timedelta(days=amount),
            "week": timedelta(weeks=amount),
            "weeks": timedelta(weeks=amount),
        }[unit]
        return reference + delta

    day_anchor = _DAY_ANCHOR_RE.fullmatch(text)
    if day_anchor:
        base = reference + {
            "today": timedelta(0),
            "tomorrow": timedelta(days=1),
            "day after tomorrow": timedelta(days=2),
            "yesterday": -timedelta(days=1),
        }[day_anchor.group("anchor").lower()]
        return _apply_optional_time(base, day_anchor.group("time"), reference)

    time_first = _TIME_FIRST_RE.fullmatch(text)
    if time_first:
        base = reference + {
            "today": timedelta(0),
            "tomorrow": timedelta(days=1),
            "day after tomorrow": timedelta(days=2),
            "yesterday": -timedelta(days=1),
        }[time_first.group("anchor").lower()]
        return _apply_time(base, time_first.group("time"))

    weekday = _WEEKDAY_RE.fullmatch(text)
    if weekday:
        target = _WEEKDAYS[weekday.group("weekday").lower()]
        days_ahead = (target - reference.weekday()) % 7
        if weekday.group("next") and days_ahead == 0:
            days_ahead = 7
        elif weekday.group("next"):
            days_ahead = days_ahead or 7
        candidate = reference + timedelta(days=days_ahead)
        result = _apply_optional_time(candidate, weekday.group("time"), reference)
        if not weekday.group("next") and days_ahead == 0 and result <= reference:
            result += timedelta(days=7)
        return result

    time_only = _TIME_ONLY_RE.fullmatch(text)
    if time_only:
        candidate = _apply_time(reference, time_only.group("time"))
        if candidate <= reference:
            candidate += timedelta(days=1)
        return candidate

    # dateutil handles conventional natural dates such as
    # "September 27 at 2pm" without inventing a new NLP dependency.
    try:
        parsed = date_parser.parse(text, default=reference.replace(microsecond=0), fuzzy=False)
    except (ValueError, OverflowError, TypeError) as exc:
        raise DeadlineParseError(f"could not parse deadline {value!r}") from exc

    return _ensure_aware(parsed, reference)


def _parse_iso(text: str, reference: datetime) -> datetime | None:
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    return _ensure_aware(parsed, reference)


def _apply_optional_time(base: datetime, time_text: str | None, reference: datetime) -> datetime:
    if time_text is None:
        return base.replace(
            hour=reference.hour,
            minute=reference.minute,
            second=reference.second,
            microsecond=0,
        )
    return _apply_time(base, time_text)


def _apply_time(base: datetime, time_text: str) -> datetime:
    try:
        parsed = date_parser.parse(time_text, default=base.replace(second=0, microsecond=0), fuzzy=False)
    except (ValueError, OverflowError, TypeError) as exc:
        raise DeadlineParseError(f"invalid deadline time {time_text!r}") from exc
    minute = parsed.minute if ":" in time_text else 0
    return base.replace(
        hour=parsed.hour,
        minute=minute,
        second=0,
        microsecond=0,
    )


def _ensure_aware(value: datetime, reference: datetime | None) -> datetime:
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value
    tz = (reference or datetime.now().astimezone()).tzinfo or timezone.utc
    return value.replace(tzinfo=tz)
