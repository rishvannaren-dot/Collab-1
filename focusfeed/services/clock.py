"""Today's date and time in India, whatever time zone the server runs in.

A server on UTC would otherwise start the next day at 05:30 in India, which
would move study cards and revision dates in the middle of the morning.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# India has no daylight saving, so a fixed offset is exact.
IST = timezone(timedelta(hours=5, minutes=30), "IST")


def zone(name):
    """The named time zone, or IST if the name is unknown or tzdata is missing."""
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError):  # ZoneInfoNotFoundError is a KeyError
        return IST


def now(tz_name="Asia/Kolkata", utc_now=None):
    return (utc_now or datetime.now(timezone.utc)).astimezone(zone(tz_name))


def today(tz_name="Asia/Kolkata", utc_now=None):
    return now(tz_name, utc_now).date()
