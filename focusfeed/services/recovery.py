"""Recovery keys: a code a student saves at sign-up to set a new password later.

The app collects no email addresses, so this replaces "email me a reset link".
Only a hash of the key is stored, and each key works once.
"""

import secrets

from werkzeug.security import check_password_hash, generate_password_hash

# No 0/O or 1/I, which are easy to misread when copied by hand.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
GROUPS, GROUP_SIZE = 4, 4  # 16 characters: 80 bits

_DUMMY_HASH = generate_password_hash("not-a-real-recovery-key")


def new_key():
    chars = "".join(secrets.choice(ALPHABET) for _ in range(GROUPS * GROUP_SIZE))
    return "-".join(chars[i : i + GROUP_SIZE] for i in range(0, len(chars), GROUP_SIZE))


def normalize(text):
    """"abcd efgh-jklm npqr" -> "ABCDEFGHJKLMNPQR": spaces, dashes and case don't matter."""
    return "".join((text or "").split()).replace("-", "").upper()


def set_key(db, user_id, now):
    """Make a new key for the user, replacing any old one. Returns the key, once."""
    key = new_key()
    db.execute(
        "INSERT INTO recovery_keys (user_id, key_hash, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET key_hash = excluded.key_hash, "
        "created_at = excluded.created_at",
        (user_id, generate_password_hash(normalize(key)), int(now)),
    )
    db.commit()
    return key


def key_created_at(db, user_id):
    """When the user's key was made (Unix time), or None if they have none."""
    row = db.execute("SELECT created_at FROM recovery_keys WHERE user_id = ?", (user_id,)).fetchone()
    return row["created_at"] if row else None


def verify(db, user_id, text):
    """True if `text` is the user's current key. `user_id` may be None (unknown user)."""
    row = None
    if user_id is not None:
        row = db.execute("SELECT key_hash FROM recovery_keys WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        # Same work as a real check, so timing doesn't reveal which usernames exist.
        check_password_hash(_DUMMY_HASH, normalize(text))
        return False
    return check_password_hash(row["key_hash"], normalize(text))


def remove_key(db, user_id):
    """Turn the user's key off (after a password change or "sign out everywhere")."""
    db.execute("DELETE FROM recovery_keys WHERE user_id = ?", (user_id,))
    db.commit()
