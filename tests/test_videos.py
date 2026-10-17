import pytest
import requests

from focusfeed.db import get_db
from focusfeed.services import videos


def video(channel="Khan Academy", seconds=600, views=50000, id="abc"):
    return {"id": id, "title": "t", "channel": channel, "seconds": seconds, "views": views}


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def fake_get(search_items, details_items, calls=None):
    def get(url, params=None, timeout=None):
        if calls is not None:
            calls.append(url)
        if url == videos.SEARCH_URL:
            return FakeResponse(payload={"items": search_items})
        return FakeResponse(payload={"items": details_items})

    return get


SEARCH_ITEMS = [
    {"id": {"videoId": "v1"}, "snippet": {"title": "Gauss's law", "channelTitle": "Khan Academy"}},
    {"id": {"videoId": "v2"}, "snippet": {"title": "Short", "channelTitle": "Khan Academy"}},
]
DETAIL_ITEMS = [
    {"id": "v1", "contentDetails": {"duration": "PT12M30S"}, "statistics": {"viewCount": "90000"}},
    {"id": "v2", "contentDetails": {"duration": "PT45S"}, "statistics": {"viewCount": "5"}},
]


@pytest.mark.parametrize(
    ("iso", "seconds"),
    (("PT45S", 45), ("PT12M30S", 750), ("PT1H2M3S", 3723), ("P0D", 0), (None, 0)),
)
def test_parse_duration(iso, seconds):
    assert videos.parse_duration(iso) == seconds


def test_format_duration():
    assert videos.format_duration(750) == "12:30"
    assert videos.format_duration(3723) == "1:02:03"


def test_filter_drops_short_long_and_unpopular():
    kept = videos.filter_videos(
        [video(id="ok"), video(seconds=50, id="short"), video(seconds=99999, id="long"), video(views=3, id="low")]
    )
    assert [v["id"] for v in kept] == ["ok"]


def test_filter_allowlist():
    allow = videos.allowed_channels()
    kept = videos.filter_videos([video(id="a"), video(channel="Random Prank Channel", id="b")], allow)
    assert [v["id"] for v in kept] == ["a"]


def test_search_youtube_parses_results():
    result = videos.search_youtube("key", "gauss", get=fake_get(SEARCH_ITEMS, DETAIL_ITEMS))
    assert result[0] == {
        "id": "v1",
        "title": "Gauss's law",
        "channel": "Khan Academy",
        "seconds": 750,
        "views": 90000,
    }
    assert len(result) == 2


def test_search_youtube_quota_error_is_friendly():
    def get(url, params=None, timeout=None):
        return FakeResponse(403, {"error": {"errors": [{"reason": "quotaExceeded"}]}})

    with pytest.raises(videos.VideoSourceError, match="limit is used up"):
        videos.search_youtube("key", "q", get=get)


def test_search_youtube_network_error_is_friendly():
    def get(url, params=None, timeout=None):
        raise requests.ConnectionError()

    with pytest.raises(videos.VideoSourceError, match="reach YouTube"):
        videos.search_youtube("key", "q", get=get)


def test_search_cached_reuses_result_then_expires(app):
    calls = []
    get = fake_get(SEARCH_ITEMS, DETAIL_ITEMS, calls)
    clock = [1000.0]
    with app.app_context():
        db = get_db()
        videos.search_cached(db, "key", "gauss", get=get, now=lambda: clock[0])
        assert len(calls) == 2  # one search + one details call
        videos.search_cached(db, "key", "gauss", get=get, now=lambda: clock[0] + 60)
        assert len(calls) == 2  # served from cache
        clock[0] += videos.CACHE_TTL_SECONDS + 1
        videos.search_cached(db, "key", "gauss", get=get, now=lambda: clock[0])
        assert len(calls) == 4  # expired, fetched again


def test_resolve_section_falls_back_to_curated_on_error(app):
    def get(url, params=None, timeout=None):
        return FakeResponse(403, {"error": {"errors": [{"reason": "quotaExceeded"}]}})

    section = {"title": "x", "query": "q", "strict": True, "tag": "electrostatics"}
    curated = [{"id": "c1", "title": "t", "channel": "Khan Academy", "tags": ["Electrostatics"]}]
    with app.app_context():
        found, notice = videos.resolve_section(
            section, get_db(), "key", curated, videos.allowed_channels(), get=get
        )
    assert [v["id"] for v in found] == ["c1"]
    assert "limit is used up" in notice


def test_resolve_section_without_key_uses_curated_only(app):
    section = {"title": "x", "query": "q", "strict": True, "tag": "electrostatics"}
    with app.app_context():
        found, notice = videos.resolve_section(section, get_db(), None, [], [])
    assert found == [] and notice is None


def test_build_sections_covers_syllabus_and_other_interests():
    prefs = {"interests": ["science-tech", "sports"], "grade": 12, "goal": "jee"}
    cards = [{"subject": "Physics", "subject_key": "physics", "slug": "electrostatics", "chapter": "Electrostatics", "query": "Electrostatics q"}]
    sections = videos.build_sections(prefs, cards)
    assert [s["title"] for s in sections] == ["Physics: Electrostatics", "Sports"]
    assert sections[0]["strict"] is True and sections[1]["strict"] is False


# Resilience


QUOTA = {"error": {"errors": [{"reason": "quotaExceeded"}]}}


def seed_videos(db, query, fetched_at):
    import json

    db.execute(
        "INSERT INTO video_cache (query, fetched_at, payload) VALUES (?, ?, ?)",
        (query, fetched_at, json.dumps([video(id="saved")])),
    )
    db.commit()


def test_saved_videos_are_shown_when_youtube_fails(app):
    def get(url, params=None, timeout=None):
        return FakeResponse(403, QUOTA)

    section = {"title": "x", "query": "q", "strict": False, "tag": "sports"}
    with app.app_context():
        db = get_db()
        seed_videos(db, "q", int(__import__("time").time()) - videos.CACHE_TTL_SECONDS - 60)
        found, notice = videos.resolve_section(section, db, "key", [], [], get=get)
        assert [v["id"] for v in found] == ["saved"]
        assert "Showing videos saved earlier." in notice
        row = db.execute("SELECT unavailable_until FROM source_status WHERE source = 'youtube'").fetchone()
        assert row[0] - __import__("time").time() > 3 * 3600 - 60  # quota pauses for 3 hours


def test_one_failure_stops_live_search_for_the_rest_of_the_page(client, app, monkeypatch):
    from tests.helpers import make_student

    app.config["YOUTUBE_API_KEY"] = "key"
    make_student(client)
    calls = []

    def failing_search(api_key, query, get=None, max_results=15):
        calls.append(query)
        raise videos.VideoSourceError("YouTube search failed.")

    monkeypatch.setattr(videos, "search_youtube", failing_search)
    assert client.get("/videos").status_code == 200
    assert len(calls) == 1  # the first section failed; no more calls on this page
    calls.clear()
    html = client.get("/videos").data.decode()
    assert calls == []  # YouTube is paused now
    assert "paused for a while" in html


def test_cached_videos_are_used_without_live_search(app):
    section = {"title": "x", "query": "q", "strict": False, "tag": "sports"}
    with app.app_context():
        db = get_db()
        seed_videos(db, "q", int(__import__("time").time()) - 3600)
        found, notice = videos.resolve_section(section, db, "key", [], [], live=False)
    assert [v["id"] for v in found] == ["saved"] and notice is None



def test_a_cache_hit_does_not_lift_a_youtube_pause(app):
    from focusfeed.services import source_health

    section = {"title": "x", "query": "q", "strict": False, "tag": "sports"}
    with app.app_context():
        db = get_db()
        seed_videos(db, "q", int(__import__("time").time()) - 60)  # fresh
        source_health.record_failure(db, "youtube", __import__("time").time(), retry_after=3 * 3600, max_wait=3 * 3600)
        videos.resolve_section(section, db, "key", [], [], get=lambda *a, **k: None)
        assert not source_health.is_available(db, "youtube", __import__("time").time())


def test_backoff_keeps_growing_past_cached_sections(app):
    from focusfeed.services import source_health

    now = __import__("time").time()
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO source_status (source, unavailable_until, failures) VALUES ('youtube', 0, 3)")
        db.commit()
        seed_videos(db, "cached", int(now) - 60)
        cached = {"title": "a", "query": "cached", "strict": False, "tag": "a"}
        failing = {"title": "b", "query": "fails", "strict": False, "tag": "b"}

        def get(url, params=None, timeout=None):
            return FakeResponse(500, {})

        videos.resolve_section(cached, db, "key", [], [], get=get)
        videos.resolve_section(failing, db, "key", [], [], get=get)
        row = db.execute("SELECT failures FROM source_status WHERE source = 'youtube'").fetchone()
    assert row[0] == 4


def test_topic_pages_respect_a_youtube_pause(client, app, monkeypatch):
    from focusfeed.services import source_health
    from tests.helpers import make_student

    app.config["YOUTUBE_API_KEY"] = "key"
    make_student(client)
    calls = []
    monkeypatch.setattr(videos, "search_youtube", lambda *a, **k: calls.append(a) or [])
    with app.app_context():
        source_health.record_failure(get_db(), "youtube", __import__("time").time(), retry_after=600)
    assert client.get("/topics/sports").status_code == 200
    assert calls == []


def test_same_named_chapters_get_different_anchors(client):
    from tests.helpers import make_student

    make_student(client, grade=11, goal="boards", interests=("sports",))
    client.post("/study/physics/thermodynamics/start")
    client.post("/study/chemistry/thermodynamics/start")
    html = client.get("/videos").data.decode()
    assert 'id="physics-thermodynamics"' in html and 'id="chemistry-thermodynamics"' in html
    today = client.get("/").data.decode()
    assert 'href="/videos#physics-thermodynamics"' in today
