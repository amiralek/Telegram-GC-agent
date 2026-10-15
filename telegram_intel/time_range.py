from datetime import datetime, time, timedelta
import re
from zoneinfo import ZoneInfo

from .models import UTC, utc
from .security import IntelError


def parse_datetime(value: str, timezone: str = "Asia/Colombo") -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            zone = ZoneInfo(timezone)
            local = parsed.replace(tzinfo=zone)
            # Reject nonexistent/ambiguous wall times instead of guessing.
            if local.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != parsed:
                raise ValueError
            if local.utcoffset() != parsed.replace(tzinfo=zone, fold=1).utcoffset():
                raise ValueError
            parsed = local
        return utc(parsed)
    except (ValueError, TypeError):
        raise IntelError("Use ISO dates/times; ambiguous local times need an explicit UTC offset.") from None


def validate_window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    try:
        start, end = utc(start), utc(end)
    except ValueError:
        raise IntelError("Datetime inputs must include a timezone.") from None
    if start >= end:
        raise IntelError("Start must be earlier than end (end is exclusive).")
    if end > datetime.now(UTC) + timedelta(minutes=1):
        raise IntelError("End must not be in the future.")
    return start, end


def window(period: str = "72h", *, timezone: str = "Asia/Colombo",
           now: datetime | None = None) -> tuple[datetime, datetime]:
    now = utc(now or datetime.now(UTC))
    local = now.astimezone(ZoneInfo(timezone))
    normalized = period.strip().lower()
    normalized = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"^(?:(?:over|for|during|in)\s+)?(?:the\s+)?(?:last|past|previous)\s+", "", normalized)
    words = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
             "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
             "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
             "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
             "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
             "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
             "eighty": 80, "ninety": 90}
    written = re.fullmatch(r"([a-z]+)(?: ([a-z]+))? (hours?|days?|weeks?)", normalized)
    if written and written[1] in words:
        number = words[written[1]]
        if written[2]:
            if number < 20 or number % 10 or written[2] not in words or not 1 <= words[written[2]] <= 9:
                raise IntelError("Unrecognized duration. Try 'seven days', 'last 48 hours' or '72h'.")
            number += words[written[2]]
        normalized = f"{number} {written[3]}"
    rolling = re.fullmatch(r"(\d+)\s*(h|hours?|d|days?|w|weeks?)", normalized)
    if rolling:
        number = int(rolling[1])
        unit = rolling[2][0]
        if not 1 <= number <= 36500:
            raise IntelError("Time window must be a positive, reasonable duration.")
        return now - timedelta(hours=number) if unit == "h" else now - timedelta(days=number * (7 if unit == "w" else 1)), now
    midnight = datetime.combine(local.date(), time.min, local.tzinfo)
    if normalized == "yesterday":
        return utc(midnight - timedelta(days=1)), utc(midnight)
    if normalized == "today":
        return utc(midnight), now
    if normalized in ("this week", "thisweek"):
        return utc(midnight - timedelta(days=local.weekday())), now
    raise IntelError("Use 24h, 48h, 72h, 'seven days', 'last 48 hours', yesterday, today or 'this week'; or --start/--end.")


def resolve_window(*, period: str | None = None, start: str | None = None,
                   end: str | None = None, timezone: str = "Asia/Colombo",
                   now: datetime | None = None) -> tuple[datetime, datetime]:
    """Deterministic local period parsing shared by raw CLI and MCP workflows."""
    if start is not None or end is not None:
        if not start or not end or period is not None:
            raise IntelError("Provide start and end together, or a period; do not combine them.")
        return validate_window(parse_datetime(start, timezone), parse_datetime(end, timezone))
    return validate_window(*window(period if period is not None else "72h", timezone=timezone, now=now))
