"""Database changes made after the original schema.sql, applied once each, in order.

schema.sql is the baseline (version 0) and is never edited again. To change the
database, append (version, [statements]) here with the next number. Each run
applies every pending batch in one transaction, and PRAGMA user_version records
the newest version applied, so existing databases are upgraded in place.
"""

MIGRATIONS = []


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
