import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from werkzeug.security import generate_password_hash

from focusfeed import migrations
from focusfeed.db import get_db
from focusfeed.routes.helpers import safe_next
from focusfeed.services import clock
from focusfeed.services.clock import today as real_today  # conftest freezes clock.today
from tests.conftest import make_app

V0_SCHEMA = Path(__file__).parent / "fixtures" / "schema_v0.sql"


def test_connections_enforce_foreign_keys_and_use_wal(app):
    with app.app_context():
        db = get_db()
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_old_database_is_upgraded_in_place(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(V0_SCHEMA.read_text())
    conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        ("demo", generate_password_hash("oldpassword1")),
    )
    conn.execute(
        "INSERT INTO preferences (user_id, interests, grade, goal) VALUES (1, 'sports', 12, 'jee')"
    )
    conn.commit()
    conn.close()

    app = make_app(tmp_path, DATABASE=str(path))
    with app.app_context():
        db = get_db()
        assert db.execute("PRAGMA user_version").fetchone()[0] == migrations.latest()
        assert db.execute("SELECT goal FROM preferences WHERE user_id = 1").fetchone()[0] == "jee"
    client = app.test_client()
    response = client.post("/auth/login", data={"username": "demo", "password": "oldpassword1"})
    assert response.headers["Location"] == "/"


def test_starting_twice_changes_nothing(tmp_path):
    make_app(tmp_path)
    app = make_app(tmp_path)
    with app.app_context():
        assert get_db().execute("PRAGMA user_version").fetchone()[0] == migrations.latest()


def test_failed_migration_is_rolled_back_completely(app, monkeypatch):
    monkeypatch.setattr(
        migrations,
        "MIGRATIONS",
        [(901, ["CREATE TABLE t1 (x)"]), (902, ["CREATE TABLE t2 (x)", "NOT SQL"])],
    )
    with app.app_context():
        db = get_db()
        before = db.execute("PRAGMA user_version").fetchone()[0]
        with pytest.raises(sqlite3.OperationalError):
            migrations.migrate(db)
        assert db.execute("PRAGMA user_version").fetchone()[0] == before
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "t1" not in tables and "t2" not in tables


def test_migrations_apply_in_order(app, monkeypatch):
    monkeypatch.setattr(
        migrations, "MIGRATIONS", [(902, ["CREATE TABLE t2 (x)"]), (901, ["CREATE TABLE t1 (x)"])]
    )
    with app.app_context():
        db = get_db()
        assert migrations.migrate(db) == 902
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"t1", "t2"} <= tables
        assert migrations.migrate(db) == 902  # nothing left to do


# The India clock


@pytest.mark.parametrize(
    ("utc", "expected"),
    (
        (datetime(2026, 10, 17, 20, 0, tzinfo=timezone.utc), date(2026, 10, 18)),  # 01:30 IST
        (datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc), date(2026, 10, 17)),  # 23:30 IST
    ),
)
def test_today_is_the_date_in_india(utc, expected):
    assert real_today(utc_now=utc) == expected


def test_unknown_time_zone_falls_back_to_india():
    assert clock.zone("Not/AZone").utcoffset(None) == timedelta(hours=5, minutes=30)


# Redirect safety


@pytest.mark.parametrize("target", ("/progress", "/#card-physics", "/study/physics/electrostatics#gauss-s-law"))
def test_safe_next_accepts_local_paths(target):
    assert safe_next(target) == target


@pytest.mark.parametrize(
    "target", ("//evil.com", "https://evil.com", "/\\evil.com", "", None, "progress", "/a\nb", 5)
)
def test_safe_next_rejects_everything_else(target):
    assert safe_next(target) == "/"


def test_tests_cannot_reach_the_network():
    with pytest.raises(Exception, match="network is disabled"):
        requests.get("https://example.com", timeout=1)


# Flash messages


def test_expired_form_on_a_post_only_route_returns_to_next(csrf_client):
    response = csrf_client.post("/auth/logout", data={"next": "/privacy"})
    assert response.headers["Location"] == "/privacy"
    response = csrf_client.post("/auth/logout", data={"next": "https://evil.com"})
    assert response.headers["Location"] == "/"


# Backups


def test_backup_keeps_the_newest_copies(app, clock_at, tmp_path):
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO users (username, password_hash) VALUES ('alice', 'x')")
        db.commit()
    dest = tmp_path / "backups"
    runner = app.test_cli_runner()
    for day in (date(2026, 10, 18), date(2026, 10, 19), date(2026, 10, 20)):
        clock_at(day)
        result = runner.invoke(args=["backup", "--dest", str(dest), "--keep", "2"])
        assert result.exit_code == 0, result.output

    copies = sorted(p.name for p in dest.iterdir())
    assert copies == ["focusfeed-2026-10-19.db", "focusfeed-2026-10-20.db"]
    for name in copies:
        path = dest / name
        assert path.stat().st_mode & 0o077 == 0
        conn = sqlite3.connect(path)
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        conn.close()
