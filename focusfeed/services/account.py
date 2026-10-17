"""Account rules and changes: nicknames, passwords, signing out other devices,
and a student's own data (download and delete)."""

import re
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,30}$")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128  # long enough for any passphrase, short enough to hash cheaply

_DUMMY_HASH = generate_password_hash("not-a-real-password")

# Shown on the privacy page and stored with each sign-up. Change it when the
# privacy notes change in a way people should agree to again.
PRIVACY_VERSION = "2026-10"

# Every table with a user_id column. Download and delete both use this list,
# and a test fails if a new table with user_id is missing from it.
USER_TABLES = ["preferences", "recovery_keys", "study_plan", "topic_progress"]
SECRET_COLUMNS = {"password_hash", "key_hash"}


def username_error(name):
    if not name:
        return "Username is required."
    if not USERNAME_RE.match(name):
        return "Pick a nickname of 3-30 letters, numbers, dots, dashes or underscores."
    return None


def password_error(password, confirm=None):
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
    if confirm is not None and password != confirm:
        return "The two passwords don't match."
    return None


def find_user(db, username):
    """Find a user by name, ignoring case. An exact-case match wins if both exist."""
    return db.execute(
        "SELECT * FROM users WHERE username = ? COLLATE NOCASE ORDER BY username = ? DESC LIMIT 1",
        (username, username),
    ).fetchone()


def username_taken(db, username):
    return find_user(db, username) is not None


def check_password(user, password):
    """True if `password` is the user's. `user` may be None (unknown user)."""
    if user is None:
        # Same work as a real check, so timing doesn't reveal which usernames exist.
        check_password_hash(_DUMMY_HASH, password)
        return False
    return check_password_hash(user["password_hash"], password)


def bump_session(db, user_id):
    """Sign out every device by moving the user's session version. Returns the new one."""
    db.execute(
        "UPDATE users SET session_version = session_version + 1 WHERE id = ?", (user_id,)
    )
    db.commit()
    return db.execute("SELECT session_version FROM users WHERE id = ?", (user_id,)).fetchone()[0]


def set_password(db, user_id, password):
    """Change the password and sign out every device. Returns the new session version."""
    db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(password), user_id),
    )
    return bump_session(db, user_id)


def iso(timestamp):
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


def export_user(db, user_id, now):
    """Everything stored about one user, as plain data (no password or key hashes)."""
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    data = {
        "app": "Focus Feed",
        "exported_at": iso(now),
        "privacy_version": PRIVACY_VERSION,
        "account": {
            "username": user["username"],
            "created_at": iso(user["created_at"]),
            "consent_at": iso(user["consent_at"]),
            "consent_version": user["consent_version"],
        },
    }
    for table in USER_TABLES:
        rows = db.execute(f"SELECT * FROM {table} WHERE user_id = ?", (user_id,)).fetchall()
        data[table] = [
            {k: row[k] for k in row.keys() if k != "user_id" and k not in SECRET_COLUMNS}
            for row in rows
        ]

    # Friendlier shapes for the two tables people will read first.
    prefs = data["preferences"][0] if data["preferences"] else None
    data["preferences"] = prefs and {
        "interests": [i for i in prefs["interests"].split(",") if i],
        "grade": prefs["grade"],
        "goal": prefs["goal"],
    }
    keys = data.pop("recovery_keys")
    data["recovery_key"] = {
        "set": bool(keys),
        "created_at": iso(keys[0]["created_at"]) if keys else None,
    }
    return data


def delete_user(db, user_id):
    """Delete the user and everything stored about them, in one transaction."""
    row = db.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return
    name = row["username"].lower()
    try:
        for table in USER_TABLES:  # rows that point at the user go first
            db.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM login_failures WHERE username IN (?, ?)", (name, "reset:" + name))
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
    except Exception:
        db.rollback()
        raise
