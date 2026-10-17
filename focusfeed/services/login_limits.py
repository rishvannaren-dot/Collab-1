"""Slow down password guessing by pausing sign-ins after repeated failures.

Failures are counted per username, so guessing one account's password is
limited no matter how many devices the guesses come from.
"""

MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60


def is_locked(db, username, now):
    """True if `username` has MAX_FAILURES failed sign-ins in the last WINDOW_SECONDS."""
    count = db.execute(
        "SELECT COUNT(*) FROM login_failures WHERE username = ? AND failed_at > ?",
        (username, now - WINDOW_SECONDS),
    ).fetchone()[0]
    return count >= MAX_FAILURES


def record_failure(db, username, now):
    # Drop old rows on the way so the table stays small.
    db.execute("DELETE FROM login_failures WHERE failed_at <= ?", (now - WINDOW_SECONDS,))
    db.execute(
        "INSERT INTO login_failures (username, failed_at) VALUES (?, ?)", (username, now)
    )
    db.commit()


def clear_failures(db, username):
    db.execute("DELETE FROM login_failures WHERE username = ?", (username,))
    db.commit()
