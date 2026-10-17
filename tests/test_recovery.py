import re

from focusfeed.db import get_db
from focusfeed.services import recovery

KEY_RE = re.compile(r"^[A-HJ-NP-Z2-9]{4}(-[A-HJ-NP-Z2-9]{4}){3}$")


def add_user(db, name="alice"):
    return db.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, 'x')", (name,)
    ).lastrowid


def test_new_keys_are_readable_and_different():
    a, b = recovery.new_key(), recovery.new_key()
    assert KEY_RE.match(a) and KEY_RE.match(b)
    assert a != b


def test_normalize_ignores_case_spaces_and_dashes():
    assert recovery.normalize("abcd efgh-jklm npqr") == "ABCDEFGHJKLMNPQR"
    assert recovery.normalize(None) == ""


def test_only_a_hash_is_stored_and_it_verifies(app):
    with app.app_context():
        db = get_db()
        uid = add_user(db)
        key = recovery.set_key(db, uid, 1000)
        stored = db.execute("SELECT key_hash FROM recovery_keys").fetchone()[0]
        assert key not in stored and recovery.normalize(key) not in stored
        assert recovery.verify(db, uid, key)
        assert recovery.verify(db, uid, key.lower().replace("-", " "))
        assert not recovery.verify(db, uid, "AAAA-AAAA-AAAA-AAAA")
        assert recovery.key_created_at(db, uid) == 1000


def test_a_new_key_replaces_the_old_one(app):
    with app.app_context():
        db = get_db()
        uid = add_user(db)
        old = recovery.set_key(db, uid, 1000)
        new = recovery.set_key(db, uid, 2000)
        assert not recovery.verify(db, uid, old)
        assert recovery.verify(db, uid, new)


def test_unknown_user_never_verifies(app):
    with app.app_context():
        db = get_db()
        assert not recovery.verify(db, None, "AAAA-AAAA-AAAA-AAAA")
        assert not recovery.verify(db, 999, "AAAA-AAAA-AAAA-AAAA")
