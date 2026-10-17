import pytest

from focusfeed import create_app
from focusfeed.db import init_db


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "test.db"),
            "SECRET_KEY": "test",
            # Most tests post forms directly; test_security.py checks CSRF with it on.
            "WTF_CSRF_ENABLED": False,
            # No Wikipedia calls from tests; pages still read the cache.
            "TOPIC_INFO_LIVE": False,
        }
    )
    with app.app_context():
        init_db()
    return app


@pytest.fixture
def client(app):
    return app.test_client()
