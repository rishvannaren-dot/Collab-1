import socket
from datetime import date

import pytest

from focusfeed import create_app
from focusfeed.db import init_db
from focusfeed.services import clock

# A Tuesday. Every test sees this as "today" unless it moves the clock.
DEFAULT_DAY = date(2026, 10, 20)


def make_app(tmp_path, **overrides):
    config = {
        "TESTING": True,
        "DATABASE": str(tmp_path / "test.db"),
        "SECRET_KEY": "test",
        # Most tests post forms directly; csrf_client keeps CSRF on.
        "WTF_CSRF_ENABLED": False,
        # No Wikipedia calls from tests; pages still read the cache.
        "TOPIC_INFO_LIVE": False,
        # Ignore a key exported on the developer's machine.
        "YOUTUBE_API_KEY": None,
    }
    config.update(overrides)
    return create_app(config)


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    """Fail any test that tries to reach the internet (mark it allow_network to opt out)."""
    if request.node.get_closest_marker("allow_network"):
        return

    def refuse(*args, **kwargs):
        raise RuntimeError("network is disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture(autouse=True)
def clock_at(monkeypatch):
    """Freeze the app's "today". Returns a function that moves it: clock_at(date(...))."""
    state = {"day": DEFAULT_DAY}
    monkeypatch.setattr(clock, "today", lambda *args, **kwargs: state["day"])

    def set_day(day):
        state["day"] = day
        return day

    return set_day


@pytest.fixture
def fixed_today():
    return DEFAULT_DAY


@pytest.fixture
def app(tmp_path):
    app = make_app(tmp_path)
    with app.app_context():
        init_db()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def csrf_client(tmp_path):
    """A client for an app with CSRF protection switched on, as in real use."""
    return make_app(tmp_path, WTF_CSRF_ENABLED=True).test_client()
