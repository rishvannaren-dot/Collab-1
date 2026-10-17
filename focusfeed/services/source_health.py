"""Back off politely when Wikipedia or YouTube fails.

After a failure the source is left alone for a while: 1 minute, then 2, 4 and
so on up to an hour, or as long as the service's Retry-After header asks. A
success resets it. This keeps pages fast during an outage and avoids hammering
a service that is rate-limiting us.
"""

BASE_BACKOFF_SECONDS = 60
MAX_BACKOFF_SECONDS = 3600


def is_available(db, source, now):
    row = db.execute(
        "SELECT unavailable_until FROM source_status WHERE source = ?", (source,)
    ).fetchone()
    return row is None or row["unavailable_until"] <= now


def record_failure(db, source, now, retry_after=None, max_wait=MAX_BACKOFF_SECONDS):
    """Pause the source. Returns how many seconds it is paused for."""
    row = db.execute("SELECT failures FROM source_status WHERE source = ?", (source,)).fetchone()
    failures = (row["failures"] if row else 0) + 1
    wait = min(retry_after or BASE_BACKOFF_SECONDS * 2 ** (failures - 1), max_wait)
    db.execute(
        "INSERT INTO source_status (source, unavailable_until, failures) VALUES (?, ?, ?) "
        "ON CONFLICT(source) DO UPDATE SET unavailable_until = excluded.unavailable_until, "
        "failures = excluded.failures",
        (source, int(now + wait), failures),
    )
    db.commit()
    return wait


def record_success(db, source):
    db.execute("DELETE FROM source_status WHERE source = ?", (source,))
    db.commit()


def retry_after_seconds(response):
    """The Retry-After header as whole seconds, or None (dates are ignored)."""
    value = getattr(response, "headers", {}).get("Retry-After", "")
    return int(value) if str(value).isdigit() else None
