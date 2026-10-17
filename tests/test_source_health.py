from focusfeed.db import get_db
from focusfeed.services import source_health


def test_backoff_doubles_and_caps(app):
    with app.app_context():
        db = get_db()
        waits = [source_health.record_failure(db, "wikipedia", 1000) for _ in range(8)]
    assert waits == [60, 120, 240, 480, 960, 1920, 3600, 3600]


def test_retry_after_wins_and_success_resets(app):
    with app.app_context():
        db = get_db()
        assert source_health.record_failure(db, "youtube", 1000, retry_after=300) == 300
        assert not source_health.is_available(db, "youtube", 1299)
        assert source_health.is_available(db, "youtube", 1300)
        source_health.record_success(db, "youtube")
        assert source_health.record_failure(db, "youtube", 2000) == 60  # back to the start


def test_custom_cap_for_quota_errors(app):
    with app.app_context():
        db = get_db()
        assert source_health.record_failure(db, "youtube", 0, retry_after=10800, max_wait=10800) == 10800


def test_unknown_sources_are_available(app):
    with app.app_context():
        assert source_health.is_available(get_db(), "anything", 0)


class Response:
    def __init__(self, headers):
        self.headers = headers


def test_retry_after_parsing():
    assert source_health.retry_after_seconds(Response({"Retry-After": "120"})) == 120
    assert source_health.retry_after_seconds(Response({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})) is None
    assert source_health.retry_after_seconds(Response({})) is None
    assert source_health.retry_after_seconds(object()) is None
