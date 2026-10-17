import json

from focusfeed.db import get_db
from focusfeed.services import account
from tests.helpers import csrf_token, login, make_student, register


def delete(client, confirm="alice", password="longenough1"):
    return client.post("/account/delete", data={"confirm_username": confirm, "current": password})


def rows_for(app, user_id):
    with app.app_context():
        db = get_db()
        counts = {t: db.execute(f"SELECT COUNT(*) FROM {t} WHERE user_id = ?", (user_id,)).fetchone()[0] for t in account.USER_TABLES}
        counts["users"] = db.execute("SELECT COUNT(*) FROM users WHERE id = ?", (user_id,)).fetchone()[0]
        counts["login_failures"] = db.execute("SELECT COUNT(*) FROM login_failures").fetchone()[0]
        return counts


# Download


def test_export_requires_login(client):
    assert client.get("/account/export").headers["Location"].endswith("/welcome")


def test_export_holds_only_your_own_rows(client, app):
    make_student(client)
    client.post("/study/mark", data={"topic_key": "physics/electrostatics/coulomb-s-law", "confidence": "2", "next": "/"})
    bob = app.test_client()
    make_student(bob, "bob", interests=("music",))
    bob.post("/study/mark", data={"topic_key": "physics/electrostatics/gauss-s-law", "confidence": "3", "next": "/"})
    data = json.loads(client.get("/account/export").data)
    assert [r["topic_key"] for r in data["topic_progress"]] == ["physics/electrostatics/coulomb-s-law"]
    assert "bob" not in json.dumps(data) and "music" not in data["preferences"]["interests"]


def test_export_has_your_data_and_no_secrets(client):
    make_student(client)
    client.post("/account/recovery-key", data={"current": "longenough1"})
    response = client.get("/account/export")
    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"]
    assert response.headers["Cache-Control"] == "no-store"
    data = json.loads(response.data)
    assert data["account"]["username"] == "alice"
    assert data["preferences"] == {"interests": ["science-tech", "sports"], "grade": 12, "goal": "jee"}
    assert data["privacy_version"] == account.PRIVACY_VERSION
    assert data["recovery_key"]["set"] is True
    for secret in (b"password_hash", b"key_hash", b"scrypt", b"pbkdf2"):
        assert secret not in response.data


# Delete


def test_delete_needs_the_password_and_the_username(client, app):
    make_student(client)
    before = rows_for(app, 1)
    assert b"isn&#39;t your current password" in delete(client, password="wrongpassword").data
    assert b"Type your username" in delete(client, confirm="bob").data
    after = rows_for(app, 1)
    assert after["users"] == 1 and after["preferences"] == before["preferences"]


def test_delete_removes_everything_and_signs_you_out(client, app):
    make_student(client)
    client.post("/account/recovery-key", data={"current": "longenough1"})
    client.post("/study/mark", data={"topic_key": "physics/electrostatics/coulomb-s-law", "confidence": "2", "next": "/"})
    bob = app.test_client()
    make_student(bob, "bob")
    bob.post("/account/recovery-key", data={"current": "longenough1"})
    bob.post("/study/mark", data={"topic_key": "physics/electrostatics/gauss-s-law", "confidence": "3", "next": "/"})
    bob_before = rows_for(app, 2)
    assert all(bob_before[t] > 0 for t in account.USER_TABLES)
    login(app.test_client(), "alice", "wrongpassword")  # a failed sign-in row for alice

    response = delete(client, confirm="ALICE")
    assert response.headers["Location"] == "/welcome"
    assert b"were deleted" in client.get("/welcome").data
    assert client.get("/").headers["Location"].endswith("/welcome")

    alice_after = rows_for(app, 1)
    assert all(alice_after[t] == 0 for t in account.USER_TABLES + ["users"])
    assert alice_after["login_failures"] == 0
    bob_after = rows_for(app, 2)
    assert {t: bob_after[t] for t in account.USER_TABLES + ["users"]} == {
        t: bob_before[t] for t in account.USER_TABLES + ["users"]
    }  # bob is untouched
    assert b"Incorrect" in login(client).data
    assert register(client).headers["Location"] == "/account/recovery-key"  # name is free again


def test_delete_signs_out_other_devices(client, app):
    make_student(client)
    other = app.test_client()
    login(other)
    delete(client)
    assert other.get("/").headers["Location"].endswith("/welcome")


def test_every_table_with_user_id_is_covered(app):
    """Fails if a new table stores user data but delete and download don't know about it."""
    with app.app_context():
        db = get_db()
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        with_user_id = {
            t for t in tables if any(col[1] == "user_id" for col in db.execute(f"PRAGMA table_info({t})"))
        }
    assert with_user_id == set(account.USER_TABLES)


def test_delete_without_csrf_token_deletes_nothing(csrf_client):
    csrf_client.post(
        "/auth/register",
        data={
            "username": "alice",
            "password": "longenough1",
            "consent": "on",
            "csrf_token": csrf_token(csrf_client, "/auth/register"),
        },
    )
    response = delete(csrf_client)
    assert response.headers["Location"] == "/account/delete"
    assert csrf_client.get("/account").status_code == 200


# Consent record


def test_sign_up_records_consent(client, app):
    register(client)
    with app.app_context():
        user = get_db().execute("SELECT * FROM users WHERE username = 'alice'").fetchone()
    assert user["consent_version"] == account.PRIVACY_VERSION
    assert user["created_at"] and user["consent_at"]
    html = client.get("/account").data.decode()
    assert f"Version {account.PRIVACY_VERSION}" in html


def test_privacy_page_shows_its_version(client):
    assert f"Version {account.PRIVACY_VERSION}".encode() in client.get("/privacy").data


def test_accounts_from_before_the_upgrade_show_not_recorded(client, app):
    with app.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO users (username, password_hash) VALUES ('old', ?)",
            ("scrypt:32768:8:1$x$y",),
        )
        db.commit()
    with client.session_transaction() as session:
        session["user_id"] = 1
    html = client.get("/account").data.decode()
    assert "Not recorded" in html and "Before October 2026" in html


# Command line


def test_cli_delete_and_export(app, client, tmp_path):
    make_student(client)
    out = tmp_path / "alice.json"
    runner = app.test_cli_runner()
    result = runner.invoke(args=["users", "export", "alice", "-o", str(out)])
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text())
    assert data["account"]["username"] == "alice"
    assert "password_hash" not in out.read_text()

    result = runner.invoke(args=["users", "delete", "alice", "--yes"])
    assert result.exit_code == 0, result.output
    assert all(count == 0 for count in rows_for(app, 1).values())


def test_cli_delete_asks_first(app, client):
    make_student(client)
    result = app.test_cli_runner().invoke(args=["users", "delete", "alice"], input="n\n")
    assert result.exit_code != 0
    assert rows_for(app, 1)["users"] == 1
