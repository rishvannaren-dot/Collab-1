"""Small helpers shared by the route modules."""

from datetime import date, datetime

from flask import current_app

from ..services import clock


def today():
    """Today's date in the app's time zone (India unless APP_TIMEZONE says otherwise)."""
    return clock.today(current_app.config["APP_TIMEZONE"])


def now():
    return clock.now(current_app.config["APP_TIMEZONE"])


def safe_next(target, default="/"):
    """Return `target` if it is a path on this site, else `default`.

    Stops a "next" form field from sending someone to another website.
    """
    if not isinstance(target, str) or not target.startswith("/") or target.startswith("//"):
        return default
    if "\\" in target or any(ord(ch) < 32 or ord(ch) == 127 for ch in target):
        return default
    return target


def format_date(value):
    """"12 Oct 2026" from a date, an ISO date string or a Unix timestamp; "" for None."""
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value, clock.zone(current_app.config["APP_TIMEZONE"]))
    elif isinstance(value, str):
        value = date.fromisoformat(value[:10])
    return f"{value.day} {value.strftime('%b %Y')}"


def short_date(value):
    """"12 Oct" from an ISO date string or a date; "" for None."""
    if not value:
        return ""
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    return f"{value.day} {value.strftime('%b')}"
