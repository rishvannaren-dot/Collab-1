import pytest

from focusfeed.db import get_db
from focusfeed.services import preferences


@pytest.fixture
def logged_in(client):
    client.post(
        "/auth/register",
        data={"username": "alice", "password": "longenough1", "consent": "on"},
    )
    client.post("/auth/login", data={"username": "alice", "password": "longenough1"})
    return client


def submit(client, **overrides):
    data = {"interests": ["science-tech", "education"], "grade": "12", "goal": "jee"}
    data.update(overrides)
    return client.post("/onboarding", data=data)


def test_onboarding_requires_login(client):
    response = client.get("/onboarding")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/welcome")


def test_new_user_is_sent_to_onboarding(logged_in):
    response = logged_in.get("/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/onboarding")


def test_onboarding_page_loads(logged_in):
    response = logged_in.get("/onboarding")
    assert response.status_code == 200
    assert b"Science &amp; Technology" in response.data


def test_saving_preferences(logged_in, app):
    response = submit(logged_in)
    assert response.headers["Location"] == "/"
    with app.app_context():
        prefs = preferences.get_preferences(get_db(), 1)
    assert prefs == {"interests": ["science-tech", "education"], "grade": 12, "goal": "jee"}
    home = logged_in.get("/")
    assert home.status_code == 200
    assert b"Grade 12" in home.data
    assert b"Science &amp; Technology" in home.data


def test_preferences_can_be_updated(logged_in, app):
    submit(logged_in)
    submit(logged_in, interests=["sports"], grade="11", goal="general")
    with app.app_context():
        prefs = preferences.get_preferences(get_db(), 1)
    assert prefs == {"interests": ["sports"], "grade": 11, "goal": "general"}
    assert b"checked" in logged_in.get("/onboarding").data


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"interests": []}, b"Pick at least one interest."),
        ({"interests": ["not-real"]}, b"Pick at least one interest."),
        ({"grade": ""}, b"Pick your grade."),
        ({"grade": "3"}, b"Pick your grade."),
        ({"goal": "nope"}, b"Pick a goal."),
    ),
)
def test_validation(logged_in, overrides, message):
    response = submit(logged_in, **overrides)
    assert response.status_code == 200
    assert message in response.data
