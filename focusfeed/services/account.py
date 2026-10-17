"""Account rules and changes: nicknames, passwords, signing out other devices."""

import re

from werkzeug.security import check_password_hash, generate_password_hash

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,30}$")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128  # long enough for any passphrase, short enough to hash cheaply

_DUMMY_HASH = generate_password_hash("not-a-real-password")


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
