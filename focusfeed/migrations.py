"""Database changes made after the original schema.sql, applied once each, in order.

schema.sql is the baseline (version 0) and is never edited again. To change the
database, append (version, [statements]) here with the next number. Each run
applies every pending batch in one transaction, and PRAGMA user_version records
the newest version applied, so existing databases are upgraded in place.
"""

MIGRATIONS = [
    (
        1,  # recovery keys, and a counter that signs out every other device
        [
            "ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0",
            "CREATE TABLE recovery_keys ("
            " user_id INTEGER PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,"
            " key_hash TEXT NOT NULL,"
            " created_at INTEGER NOT NULL)",
        ],
    ),
    (
        2,  # when the account was made and which privacy notes were agreed to
        [
            "ALTER TABLE users ADD COLUMN created_at INTEGER",
            "ALTER TABLE users ADD COLUMN consent_at INTEGER",
            "ALTER TABLE users ADD COLUMN consent_version TEXT",
        ],
    ),
    (
        3,  # each student's week plan: the chapter each subject is on and since when
        [
            "CREATE TABLE study_plan ("
            " user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,"
            " subject_key TEXT NOT NULL,"
            " chapter_index INTEGER NOT NULL,"
            " start_on TEXT NOT NULL,"
            " PRIMARY KEY (user_id, subject_key))",
        ],
    ),
    (
        4,  # topics a student marked as studied, how sure they felt, and revision dates
        [
            "CREATE TABLE topic_progress ("
            " user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,"
            " topic_key TEXT NOT NULL,"
            " confidence INTEGER NOT NULL CHECK (confidence IN (1, 2, 3)),"
            " first_studied_on TEXT NOT NULL,"
            " last_studied_on TEXT NOT NULL,"
            " box INTEGER NOT NULL DEFAULT 0 CHECK (box BETWEEN 0 AND 5),"
            " due_on TEXT,"
            " PRIMARY KEY (user_id, topic_key))",
            "CREATE INDEX topic_progress_due ON topic_progress (user_id, due_on)",
        ],
    ),
]


def latest():
    return max((version for version, _ in MIGRATIONS), default=0)


def migrate(db):
    """Apply pending migrations. On any error nothing is applied and the error is raised."""
    current = db.execute("PRAGMA user_version").fetchone()[0]
    if not any(version > current for version, _ in MIGRATIONS):
        return current

    db.execute("BEGIN IMMEDIATE")
    try:
        # Another process may have migrated while we waited for the lock.
        current = db.execute("PRAGMA user_version").fetchone()[0]
        for version, statements in sorted(MIGRATIONS):
            if version <= current:
                continue
            # One statement at a time: executescript() would commit on its own.
            for sql in statements:
                db.execute(sql)
            db.execute(f"PRAGMA user_version = {int(version)}")
            current = version
        db.commit()
    except Exception:
        db.rollback()
        raise
    return current
