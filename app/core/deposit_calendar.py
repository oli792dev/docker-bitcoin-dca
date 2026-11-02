"""Monthly deposit instants in the configured local timezone."""

import calendar
from datetime import UTC, datetime, tzinfo


def deposit_at(year: int, month: int, day: int, clock: str, zone: tzinfo) -> datetime:
    hour, minute = map(int, clock.split(":"))
    wall = datetime(year, month, min(day, calendar.monthrange(year, month)[1]), hour, minute, tzinfo=zone, fold=0)
    # Pick the first repeated hour; move nonexistent wall times forward by the gap.
    return wall.astimezone(UTC).astimezone(zone) if zone is not None else wall
