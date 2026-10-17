import pytest

from focusfeed import load_secret_key
from focusfeed.db import get_db
from focusfeed.services import login_limits
from tests.helpers import csrf_token


def register(client, username="alice", password="longenough1"):
    return client.post(
        "/auth/register",
        data={"username": username, "password": password, "consent": "on"},
    )


def login(client, username="alice", password="longenough1"):
    return client.post("/auth/login", data={"username": username, "password": password})


# Failed sign-in limit


def test_login_locks_after_repeated_failures(client):
    register(client)
    client.post("/auth/logout")
    for _ in range(login_limits.MAX_FAILURES):
        login(client, password="wrongpassword")
    response = login(client)  # right password, but too late
    assert b"Too many failed sign-ins" in response.data
    assert client.get("/").headers["Location"].endswith("/welcome")


def test_lock_only_affects_that_username(client):
    register(client)
    register(client, "bob")
    for _ in range(login_limits.MAX_FAILURES):
        login(client, password="wrongpassword")
    assert login(client, "bob").headers["Location"] == "/"


def test_successful_login_clears_failures(client, app):
    register(client)
    for _ in range(login_limits.MAX_FAILURES - 1):
        login(client, password="wrongpassword")
    assert login(client).headers["Location"] == "/"
    with app.app_context():
        count = get_db().execute("SELECT COUNT(*) FROM login_failures").fetchone()[0]
    assert count == 0


def test_lock_expires_after_window(app):
    start = 1_000_000
    with app.app_context():
        db = get_db()
        for _ in range(login_limits.MAX_FAILURES):
            login_limits.record_failure(db, "alice", start)
        assert login_limits.is_locked(db, "alice", start + 1)
        assert not login_limits.is_locked(db, "alice", start + login_limits.WINDOW_SECONDS)


# CSRF protection


def test_form_without_csrf_token_is_rejected(csrf_client):
    response = register(csrf_client)
    assert response.headers["Location"] == "/auth/register"
    assert b"That form expired" in csrf_client.get("/auth/register").data

    # No account was created.
    response = csrf_client.post(
        "/auth/login",
        data={
            "username": "alice",
            "password": "longenough1",
            "csrf_token": csrf_token(csrf_client, "/auth/login"),
        },
    )
    assert b"Incorrect username or password." in response.data


def test_forms_work_with_csrf_token(csrf_client):
    account = {"username": "alice", "password": "longenough1"}
    response = csrf_client.post(
        "/auth/register",
        data={**account, "consent": "on", "csrf_token": csrf_token(csrf_client, "/auth/register")},
    )
    assert response.headers["Location"] == "/account/recovery-key"
    csrf_client.post("/auth/logout", data={"csrf_token": csrf_token(csrf_client, "/account")})

    response = csrf_client.post(
        "/auth/login", data={**account, "csrf_token": csrf_token(csrf_client, "/auth/login")}
    )
    assert response.headers["Location"] == "/"

    response = csrf_client.post(
        "/onboarding",
        data={
            "interests": ["sports"],
            "grade": "12",
            "goal": "jee",
            "csrf_token": csrf_token(csrf_client, "/onboarding"),
        },
    )
    assert response.headers["Location"] == "/"

    response = csrf_client.post(
        "/auth/logout", data={"csrf_token": csrf_token(csrf_client, "/")}
    )
    assert response.status_code == 302
    assert csrf_client.get("/").headers["Location"].endswith("/welcome")


def test_logout_without_csrf_token_keeps_you_signed_in(csrf_client):
    account = {"username": "alice", "password": "longenough1"}
    csrf_client.post(
        "/auth/register",
        data={**account, "consent": "on", "csrf_token": csrf_token(csrf_client, "/auth/register")},
    )
    csrf_client.post(
        "/auth/login", data={**account, "csrf_token": csrf_token(csrf_client, "/auth/login")}
    )
    response = csrf_client.post("/auth/logout")
    assert response.headers["Location"] == "/"
    assert csrf_client.get("/").headers["Location"].endswith("/onboarding")


# Session cookie and secret key


def test_session_cookie_flags(client):
    register(client)
    cookie = login(client).headers["Set-Cookie"]
    assert "SameSite=Lax" in cookie
    assert "HttpOnly" in cookie


def test_secret_key_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "from-env")
    assert load_secret_key(str(tmp_path)) == "from-env"
    assert not (tmp_path / "secret_key").exists()


@pytest.mark.parametrize("value", (None, "", "change-me"))
def test_secret_key_is_generated_and_kept(tmp_path, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("SECRET_KEY", value)
    key = load_secret_key(str(tmp_path))
    assert len(key) == 64
    assert load_secret_key(str(tmp_path)) == key  # same key after a restart
    assert (tmp_path / "secret_key").stat().st_mode & 0o077 == 0  # owner-only
