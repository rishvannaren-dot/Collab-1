import pytest
import requests

from focusfeed.db import get_db
from focusfeed.services import cards, explore, preferences, topic_info


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

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
        assert topic_info.lookup_many(db, [search()], get=failing) == {"Physics: Transformers": None}
        calls = []
        topic_info.lookup_many(db, [search()], get=fake_get(lambda p: page("Transformer"), calls))
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
