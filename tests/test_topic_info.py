import json
import threading
import time

import pytest
import requests

from focusfeed.db import get_db
from focusfeed.services import cards, explore, preferences, topic_info


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


def page(title, extract="X is a thing. It does stuff.", **extra):
    url = "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")
    return {"query": {"pages": [{"title": title, "extract": extract, "fullurl": url, **extra}]}}


def fake_get(answer, calls=None):
    """`answer(params)` returns the JSON payload for one request."""

    def get(url, params=None, headers=None, timeout=None):
        if calls is not None:
            calls.append({"params": params, "headers": headers})
        return FakeResponse(payload=answer(params))

    return get


def search(key="Physics: Transformers", title="Transformer", query="Transformers", context="Physics"):
    return {"key": key, "title": title, "query": query, "context": context}


# Trimming Wikipedia's intro to one or two lines


def test_summary_keeps_two_sentences_and_drops_empty_brackets():
    text = "Osmotic pressure ( ) is the minimum pressure. It stops inward flow. A third sentence."
    assert topic_info.short_summary(text) == (
        "Osmotic pressure is the minimum pressure. It stops inward flow."
    )


def test_summary_stops_before_math_markup():
    text = "A matrix is a rectangular array of numbers. For example, {\\displaystyle A} is one."
    assert topic_info.short_summary(text) == "A matrix is a rectangular array of numbers."


def test_summary_cuts_one_very_long_sentence():
    summary = topic_info.short_summary("word " * 200)
    assert summary.endswith("…")
    assert len(summary) <= topic_info.MAX_CHARS + 1


def test_summary_of_nothing_is_empty():
    assert topic_info.short_summary(None) == ""


# Fetching


def test_fetch_uses_mapped_title_first():
    calls = []
    found = topic_info.fetch_summary(search(), get=fake_get(lambda p: page("Transformer"), calls))
    assert found == {
        "title": "Transformer",
        "summary": "X is a thing. It does stuff.",
        "url": "https://en.wikipedia.org/wiki/Transformer",
    }
    assert len(calls) == 1
    assert calls[0]["params"]["titles"] == "Transformer"
    assert "FocusFeed" in calls[0]["headers"]["User-Agent"]


def test_fetch_falls_back_to_search_when_title_is_missing():
    def answer(params):
        if "titles" in params:
            return {"query": {"pages": [{"title": "Transformer", "missing": True}]}}
        return page("Transformer")

    calls = []
    found = topic_info.fetch_summary(search(), get=fake_get(answer, calls))
    assert found["title"] == "Transformer"
    assert calls[1]["params"]["gsrsearch"] == "Transformers"


def test_fetch_retries_with_subject_after_a_disambiguation_page():
    def answer(params):
        if params["gsrsearch"] == "Interference":
            return page("Interference", pageprops={"disambiguation": ""})
        return page("Wave interference")

    calls = []
    s = search(key="Physics: Interference", title=None, query="Interference")
    found = topic_info.fetch_summary(s, get=fake_get(answer, calls))
    assert found["title"] == "Wave interference"
    assert [c["params"]["gsrsearch"] for c in calls] == ["Interference", "Interference Physics"]


def test_fetch_returns_none_when_nothing_matches():
    get = fake_get(lambda p: {"query": {}})
    assert topic_info.fetch_summary(search(title=None), get=get) is None


@pytest.mark.parametrize("status", (429, 500))
def test_fetch_error_status_raises(status):
    def get(url, params=None, headers=None, timeout=None):
        return FakeResponse(status)

    with pytest.raises(topic_info.InfoSourceError):
        topic_info.fetch_summary(search(), get=get)


def test_fetch_network_error_raises():
    def get(url, params=None, headers=None, timeout=None):
        raise requests.ConnectionError()

    with pytest.raises(topic_info.InfoSourceError, match="reach Wikipedia"):
        topic_info.fetch_summary(search(), get=get)


# Caching


def test_lookup_caches_results_then_expires(app):
    calls = []
    get = fake_get(lambda p: page("Transformer"), calls)
    clock = [1000.0]
    with app.app_context():
        db = get_db()
        first = topic_info.lookup_many(db, [search()], get=get, now=lambda: clock[0])
        assert first["Physics: Transformers"]["title"] == "Transformer"
        assert len(calls) == 1
        topic_info.lookup_many(db, [search()], get=get, now=lambda: clock[0] + 60)
        assert len(calls) == 1  # from the cache
        clock[0] += topic_info.CACHE_TTL_SECONDS + 1
        topic_info.lookup_many(db, [search()], get=get, now=lambda: clock[0])
        assert len(calls) == 2  # expired, fetched again


def test_lookup_does_not_cache_failures(app):
    def failing(url, params=None, headers=None, timeout=None):
        return FakeResponse(429)

    with app.app_context():
        db = get_db()
        result = topic_info.lookup_many(db, [search()], get=failing, now=lambda: 1000)
        assert result == {"Physics: Transformers": None}
        calls = []
        good = fake_get(lambda p: page("Transformer"), calls)
        topic_info.lookup_many(db, [search()], get=good, now=lambda: 1030)
        assert calls == []  # Wikipedia is paused for a minute after a failure
        topic_info.lookup_many(db, [search()], get=good, now=lambda: 1061)
        assert len(calls) == 1  # tried again


def test_lookup_caches_no_match(app):
    calls = []
    get = fake_get(lambda p: {"query": {}}, calls)
    with app.app_context():
        db = get_db()
        topic_info.lookup_many(db, [search()], get=get)
        count = len(calls)
        assert topic_info.lookup_many(db, [search()], get=get) == {"Physics: Transformers": None}
        assert len(calls) == count


def test_lookup_respects_live_limit(app):
    calls = []
    get = fake_get(lambda p: page("Thing"), calls)
    searches = [search(key=f"k{n}") for n in range(5)]
    with app.app_context():
        result = topic_info.lookup_many(get_db(), searches, get=get, live=2)
    assert sum(1 for v in result.values() if v) == 2
    assert len(calls) == 2


# Data files


def test_every_mapped_topic_is_in_the_syllabus():
    syllabus = cards.load_syllabus()
    topics = {t for s in syllabus["subjects"].values() for c in s["chapters"] for t in c["topics"]}
    assert set(topic_info.load_wiki_titles()) - topics == set()


def test_syllabus_search_uses_mapped_title():
    s = topic_info.syllabus_search("Transformers", "Physics", topic_info.load_wiki_titles())
    assert s["title"] == "Transformer"
    assert s["key"] == "Physics: Transformers"


def test_every_interest_has_topics_to_explore():
    topics = explore.load_interest_topics()
    assert set(topics) == set(preferences.INTERESTS)
    assert all(len(articles) >= 4 for articles in topics.values())


# Resilience


def failing_get(status=503, headers=None, calls=None):
    def get(url, params=None, headers_=None, timeout=None, **kwargs):
        if calls is not None:
            calls.append(params)
        return FakeResponse(status, headers=headers)

    return get


def seed_cache(db, key, fetched_at, title="Transformer"):
    payload = json.dumps({"title": title, "summary": "Saved summary.", "url": "https://en.wikipedia.org/wiki/x"})
    db.execute("INSERT INTO topic_info (key, fetched_at, payload) VALUES (?, ?, ?)", (key, fetched_at, payload))
    db.commit()


def test_an_expired_summary_is_kept_when_wikipedia_fails(app):
    old = 1_000_000
    later = old + topic_info.CACHE_TTL_SECONDS + 10
    with app.app_context():
        db = get_db()
        seed_cache(db, "Physics: Transformers", old)
        result = topic_info.lookup_many(db, [search()], get=failing_get(), now=lambda: later)
        assert result["Physics: Transformers"]["summary"] == "Saved summary."
        assert result["Physics: Transformers"]["checked_on"] == "1970-01-12"
        row = db.execute("SELECT fetched_at FROM topic_info").fetchone()
        assert row[0] == old  # not overwritten


def test_very_old_summaries_are_dropped(app):
    old = 1_000_000
    with app.app_context():
        db = get_db()
        seed_cache(db, "Physics: Transformers", old)
        later = old + topic_info.STALE_MAX_SECONDS + 10
        assert topic_info.lookup_many(db, [search()], get=failing_get(), now=lambda: later) == {"Physics: Transformers": None}


def test_retry_after_is_respected(app):
    calls = []
    with app.app_context():
        db = get_db()
        topic_info.lookup_many(db, [search()], get=failing_get(429, {"Retry-After": "120"}), now=lambda: 1000)
        row = db.execute("SELECT unavailable_until FROM source_status WHERE source = 'wikipedia'").fetchone()
        assert row[0] == 1120
        good = fake_get(lambda p: page("Transformer"), calls)
        topic_info.lookup_many(db, [search()], get=good, now=lambda: 1060)
        assert calls == []
        topic_info.lookup_many(db, [search()], get=good, now=lambda: 1121)
        assert len(calls) == 1
        assert topic_info.source_busy(db, 1122) is False  # success clears the pause


def test_one_failure_stops_the_batch(app):
    calls = []
    searches = [search(key=f"k{n}", title=None, query=f"q{n}") for n in range(10)]
    with app.app_context():
        topic_info.lookup_many(get_db(), searches, get=failing_get(calls=calls), live=10, now=lambda: 1000)
    assert len(calls) <= topic_info.MAX_WORKERS


def test_slow_wikipedia_never_holds_the_page(app):
    release = threading.Event()

    def slow_get(url, params=None, headers=None, timeout=None):
        release.wait(5)
        return FakeResponse(payload=page("Transformer"))

    with app.app_context():
        db = get_db()
        started = time.monotonic()
        result = topic_info.lookup_many(db, [search()], get=slow_get, budget=0.2, now=lambda: 1000)
        elapsed = time.monotonic() - started
        assert elapsed < 1
        assert result == {"Physics: Transformers": None}
        assert db.execute("SELECT COUNT(*) FROM topic_info").fetchone()[0] == 0
        assert topic_info.source_busy(db, 1001)  # a timeout pauses Wikipedia too
    release.set()


def test_results_carry_the_checked_date(app):
    with app.app_context():
        result = topic_info.lookup_many(
            get_db(), [search()], get=fake_get(lambda p: page("Transformer")), now=lambda: 1_760_000_000
        )
    assert result["Physics: Transformers"]["checked_on"] == "2025-10-09"


def test_cache_is_read_with_one_query(app):
    statements = []
    searches = [search(key=f"k{n}") for n in range(6)]
    with app.app_context():
        db = get_db()
        for s in searches:
            seed_cache(db, s["key"], 1000)
        db.set_trace_callback(statements.append)
        topic_info.lookup_many(db, searches, live=0, now=lambda: 1001)
        db.set_trace_callback(None)
    assert sum(1 for s in statements if s.startswith("SELECT key, fetched_at, payload FROM topic_info")) == 1
