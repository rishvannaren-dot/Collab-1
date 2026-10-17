import pytest

from focusfeed.db import get_db


def register(client, username="alice", password="longenough1"):
    return client.post(
        "/auth/register",
        data={"username": username, "password": password, "consent": "on"},
    )


def login(client, username="alice", password="longenough1"):
    return client.post("/auth/login", data={"username": username, "password": password})


def test_register_page_loads(client):
    assert client.get("/auth/register").status_code == 200


def test_register_stores_hashed_password(client, app):
    response = register(client)
    # Sign-up signs you in and offers a recovery key next.
    assert response.headers["Location"].endswith("/account/recovery-key")
    with app.app_context():
        row = get_db().execute("SELECT * FROM users WHERE username = 'alice'").fetchone()
    assert row is not None
    assert row["password_hash"] != "longenough1"
    assert "longenough1" not in row["password_hash"]


@pytest.mark.parametrize(
    ("username", "password", "message"),
    (
        ("", "longenough1", b"Username is required."),
        ("alice", "short", b"at least 8 characters"),
    ),
)
def test_register_validation(client, username, password, message):
    response = register(client, username, password)
    assert message in response.data


def test_register_requires_consent(client):
    response = client.post(
        "/auth/register", data={"username": "alice", "password": "longenough1"}
    )
    assert b"parent or guardian" in response.data


def test_register_duplicate_username(client):
    register(client)
    response = register(client)
    assert b"already taken" in response.data


def test_login_and_access_home(client):
    register(client)
    response = login(client)
    assert response.headers["Location"] == "/"
    response = client.get("/")
    assert response.headers["Location"].endswith("/onboarding")
    response = client.get("/onboarding")
    assert response.status_code == 200
    assert b"alice" in response.data


@pytest.mark.parametrize(
    ("username", "password"),
    (("nobody", "longenough1"), ("alice", "wrongpassword")),
)
def test_login_rejects_bad_credentials(client, username, password):
    register(client)
    response = login(client, username, password)
    assert b"Incorrect username or password." in response.data


def test_logout(client):
    register(client)
    login(client)
    response = client.post("/auth/logout")
    assert response.status_code == 302
    assert client.get("/").status_code == 302
