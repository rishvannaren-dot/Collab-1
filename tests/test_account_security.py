import re

import pytest

from focusfeed.db import get_db
from focusfeed.services import login_limits
from tests.helpers import csrf_token, login, register

KEY_RE = re.compile(r'class="key"[^>]*>([A-Z0-9-]{19})<')


def make_key(client, password="longenough1"):
    response = client.post("/account/recovery-key", data={"current": password})
    match = KEY_RE.search(response.data.decode())
    return match.group(1) if match else None


def forgot(client, key, username="alice", password="brandnewpass1", confirm=None):
    return client.post(
        "/auth/forgot",
        data={
            "username": username,
            "recovery_key": key,
            "password": password,
            "confirm": password if confirm is None else confirm,
        },
    )


def password_hash(app, username="alice"):
    with app.app_context():
        return get_db().execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()[0]


# Sign-up and the recovery key


def test_sign_up_signs_you_in_and_offers_a_key(client):
    assert register(client).headers["Location"] == "/account/recovery-key"
    assert client.get("/onboarding").status_code == 200
    page = client.get("/account/recovery-key").data.decode()
    assert "Skip for now" in page and 'href="/onboarding"' in page


def test_making_a_key_needs_your_password(client):
    register(client)
    response = client.post("/account/recovery-key", data={"current": "wrongpassword"})
    assert not KEY_RE.search(response.data.decode())
    assert b"isn&#39;t your current password" in response.data

    response = client.post("/account/recovery-key", data={"current": "longenough1"})
    assert response.headers["Cache-Control"] == "no-store"
    assert KEY_RE.search(response.data.decode())


def test_today_reminds_you_until_you_have_a_key(client):
    register(client)
    client.post("/onboarding", data={"interests": ["sports"], "grade": "12", "goal": "jee"})
    assert b"Set up a recovery key" in client.get("/").data
    make_key(client)
    assert b"Set up a recovery key" not in client.get("/").data


# Forgot password


def test_reset_with_the_key_changes_the_password_and_the_key(client):
    register(client)
    key = make_key(client)
    client.post("/auth/logout")

    response = forgot(client, key)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    new_key = KEY_RE.search(response.data.decode()).group(1)
    assert new_key != key
    assert client.get("/").headers["Location"].endswith("/onboarding")  # signed in

    client.post("/auth/logout")
    assert b"Incorrect" in login(client, password="longenough1").data
    assert login(client, password="brandnewpass1").headers["Location"] == "/"
    client.post("/auth/logout")
    assert b"don&#39;t match" in forgot(client, key, password="anotherpass1").data


def test_unknown_user_and_wrong_key_look_the_same(client):
    register(client)
    make_key(client)
    client.post("/auth/logout")
    wrong_key = forgot(client, "AAAA-AAAA-AAAA-AAAA").data.decode()
    unknown = forgot(client, "AAAA-AAAA-AAAA-AAAA", username="nobody").data.decode()
    message = "That username and recovery key don&#39;t match."
    assert message in wrong_key and message in unknown


def test_reset_locks_after_five_wrong_keys(client, app):
    register(client)
    key = make_key(client)
    client.post("/auth/logout")
    for _ in range(login_limits.MAX_FAILURES):
        forgot(client, "AAAA-AAAA-AAAA-AAAA")
    response = forgot(client, key)
    assert b"Too many tries" in response.data
    assert login(client, password="longenough1").headers["Location"] == "/"  # unchanged


def test_bad_new_password_changes_nothing_and_counts_no_failure(client, app):
    register(client)
    key = make_key(client)
    client.post("/auth/logout")
    before = password_hash(app)
    assert b"at least 8" in forgot(client, key, password="short").data
    assert b"don&#39;t match" in forgot(client, key, confirm="different12").data
    assert password_hash(app) == before
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM login_failures").fetchone()[0] == 0


def test_a_locked_sign_in_does_not_block_a_reset(client):
    register(client)
    key = make_key(client)
    client.post("/auth/logout")
    for _ in range(login_limits.MAX_FAILURES):
        login(client, password="wrongpassword")
    assert forgot(client, key).status_code == 200
    client.post("/auth/logout")
    assert login(client, password="brandnewpass1").headers["Location"] == "/"


# Signing out other devices


@pytest.fixture
def two_devices(app):
    a, b = app.test_client(), app.test_client()
    register(a)
    login(b)
    assert b.get("/").headers["Location"].endswith("/onboarding")  # b is signed in
    return a, b


def test_changing_password_signs_out_other_devices(two_devices):
    a, b = two_devices
    response = a.post(
        "/account/password",
        data={"current": "longenough1", "password": "brandnewpass1", "confirm": "brandnewpass1"},
    )
    assert response.headers["Location"] == "/account"
    assert b"flash-success" in a.get("/account").data
    assert a.get("/").headers["Location"].endswith("/onboarding")  # still signed in
    assert b.get("/").headers["Location"].endswith("/welcome")


def test_reset_signs_out_other_devices(app, two_devices):
    a, b = two_devices
    key = make_key(a)
    reset = app.test_client()
    forgot(reset, key)
    assert b.get("/").headers["Location"].endswith("/welcome")
    assert a.get("/").headers["Location"].endswith("/welcome")


def test_sign_out_everywhere_keeps_this_device(two_devices):
    a, b = two_devices
    assert a.post("/account/sign-out-everywhere").headers["Location"] == "/account"
    assert a.get("/").headers["Location"].endswith("/onboarding")
    assert b.get("/").headers["Location"].endswith("/welcome")


def test_sessions_from_before_the_upgrade_still_work(client):
    register(client)
    with client.session_transaction() as session:
        del session["sv"]
    assert client.get("/onboarding").status_code == 200


def test_wrong_current_password_changes_nothing(client, app):
    register(client)
    before = password_hash(app)
    response = client.post(
        "/account/password",
        data={"current": "wrongpassword", "password": "brandnewpass1", "confirm": "brandnewpass1"},
    )
    assert response.status_code == 200
    assert password_hash(app) == before


def test_wrong_passwords_on_account_pages_count_as_failed_sign_ins(client):
    register(client)
    for _ in range(login_limits.MAX_FAILURES):
        client.post("/account/recovery-key", data={"current": "wrongpassword"})
    response = client.post("/account/recovery-key", data={"current": "longenough1"})
    assert b"Too many wrong passwords" in response.data
    assert not KEY_RE.search(response.data.decode())


# Nicknames


def test_usernames_ignore_case(client, app):
    register(client, "Alice")
    client.post("/auth/logout")
    assert login(client, "alice").headers["Location"] == "/"
    client.post("/auth/logout")
    assert b"already taken" in register(client, "ALICE").data


def test_failures_for_any_case_share_one_lock(client):
    register(client, "Alice")
    client.post("/auth/logout")
    for name in ("alice", "ALICE", "Alice", "aLiCe", "alicE"):
        login(client, name, "wrongpassword")
    assert b"Too many failed sign-ins" in login(client, "alice").data


@pytest.mark.parametrize("name", ("ab", "has space", "x" * 31, "émile", "<script>"))
def test_bad_nicknames_are_rejected(client, name):
    response = register(client, name)
    assert response.status_code == 200
    assert b"Pick a nickname" in response.data


def test_long_passwords_are_rejected(client):
    assert b"at most 128" in register(client, password="x" * 129).data


# Sign-in page details


def test_keep_me_signed_in(client, app):
    register(client)
    client.post("/auth/logout")
    remembered = client.post(
        "/auth/login", data={"username": "alice", "password": "longenough1", "remember": "on"}
    )
    assert "Expires=" in remembered.headers["Set-Cookie"]
    other = app.test_client()
    plain = login(other)
    assert "Expires=" not in plain.headers["Set-Cookie"]


def test_sign_in_page_has_forgot_link_and_password_toggle(client):
    html = client.get("/auth/login").data.decode()
    assert "Forgot password?" in html
    assert 'autocapitalize="none"' in html
    assert "data-password-toggle" in html


# CSRF on the new forms


def test_new_forms_reject_missing_csrf_tokens(csrf_client):
    assert csrf_client.post("/auth/forgot", data={}).headers["Location"] == "/auth/forgot"
    csrf_client.post(
        "/auth/register",
        data={
            "username": "alice",
            "password": "longenough1",
            "consent": "on",
            "csrf_token": csrf_token(csrf_client, "/auth/register"),
        },
    )
    response = csrf_client.post(
        "/account/password",
        data={"current": "longenough1", "password": "brandnewpass1", "confirm": "brandnewpass1"},
    )
    assert response.headers["Location"] == "/account/password"
    response = csrf_client.post("/account/sign-out-everywhere", data={"next": "/account"})
    assert response.headers["Location"] == "/account"
    assert csrf_client.get("/account").status_code == 200  # still signed in
    csrf_client.post("/auth/logout", data={"csrf_token": csrf_token(csrf_client, "/account")})
    response = csrf_client.post(
        "/auth/login",
        data={
            "username": "alice",
            "password": "longenough1",
            "csrf_token": csrf_token(csrf_client, "/auth/login"),
        },
    )
    assert response.headers["Location"] == "/"  # the old password still works


# Command line


def test_cli_set_password(app, client):
    register(client)
    client.post("/auth/logout")
    runner = app.test_cli_runner()
    result = runner.invoke(args=["users", "set-password", "ALICE"], input="newpassword1\nnewpassword1\n")
    assert result.exit_code == 0, result.output
    assert login(client, password="newpassword1").headers["Location"] == "/"


@pytest.mark.parametrize(
    ("args", "stdin"),
    ((["users", "set-password", "nobody"], "newpassword1\nnewpassword1\n"), (["users", "set-password", "alice"], "short\nshort\n")),
)
def test_cli_set_password_errors(app, client, args, stdin):
    register(client)
    result = app.test_cli_runner().invoke(args=args, input=stdin)
    assert result.exit_code != 0


def test_cli_unlock(app, client):
    register(client)
    client.post("/auth/logout")
    for _ in range(login_limits.MAX_FAILURES):
        login(client, password="wrongpassword")
    assert b"Too many" in login(client).data
    result = app.test_cli_runner().invoke(args=["users", "unlock", "alice"])
    assert result.exit_code == 0, result.output
    assert login(client).headers["Location"] == "/"
