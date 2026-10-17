import time
from datetime import date

import pytest

from focusfeed.db import get_db
from focusfeed.services import cards, explore, topic_info


@pytest.fixture
def student(client):
    client.post(
        "/auth/register",
        data={"username": "alice", "password": "longenough1", "consent": "on"},
    )
    client.post("/auth/login", data={"username": "alice", "password": "longenough1"})
    client.post(
        "/onboarding",
        data={"interests": ["science-tech", "sports"], "grade": "12", "goal": "jee"},
    )
    return client


def todays_cards():
    prefs = {"interests": ["science-tech", "sports"], "grade": 12, "goal": "jee"}
    return cards.build_cards(prefs, cards.load_syllabus(), date.today())


def cache(app, key, summary, title="Some article"):
    """Put a summary in the cache as if Wikipedia had answered."""
    url = "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")
    with app.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO topic_info (key, fetched_at, payload) VALUES (?, ?, ?)",
            (key, int(time.time()), f'{{"title": "{title}", "summary": "{summary}", "url": "{url}"}}'),
        )
        db.commit()


# Followed topics


def test_sidebar_topics_are_links(student):
    html = student.get("/").data.decode()
    assert 'href="/topics/sports"' in html
    assert 'href="/topics/science-tech"' in html


def test_topic_page_shows_only_that_topic(student):
    response = student.get("/topics/sports")
    assert response.status_code == 200
    html = response.data.decode()
    assert "<h1>Sports</h1>" in html
    assert "Cricket" in html and "Association football" in html
    assert "Raga" not in html  # music, which they don't follow
    assert "You follow this" in html
    assert "Today&#39;s pick" in html or "Today's pick" in html
    assert "Search YouTube for Sports" in html
    assert 'class="followed-link active" href="/topics/sports"' in html


def test_topic_page_for_unfollowed_topic(student):
    html = student.get("/topics/music").data.decode()
    assert "You don&#39;t follow this yet" in html or "You don't follow this yet" in html


def test_topic_page_shows_cached_summary(student, app):
    cache(app, "Sports: Cricket", "Cricket is a bat-and-ball game.", "Cricket")
    html = student.get("/topics/sports").data.decode()
    assert "Cricket is a bat-and-ball game." in html
    assert "https://en.wikipedia.org/wiki/Cricket" in html


def test_unknown_topic_is_404(student):
    assert student.get("/topics/astrology").status_code == 404


def test_topic_page_requires_login(client):
    assert client.get("/topics/sports").headers["Location"].endswith("/welcome")


# Chapter pages


def test_card_title_and_chips_link_to_the_chapter_page(student):
    card = todays_cards()[0]
    html = student.get("/").data.decode()
    chapter_url = f"/study/{card['subject_key']}/{card['slug']}"
    assert f'href="{chapter_url}#{cards.slugify(card["topic"])}"' in html
    for topic in card["topics"]:
        assert f'href="{chapter_url}#{cards.slugify(topic)}"' in html


def test_chapter_page_lists_every_topic_and_marks_today(student):
    card = todays_cards()[0]
    response = student.get(f"/study/{card['subject_key']}/{card['slug']}")
    assert response.status_code == 200
    html = response.data.decode()
    assert card["chapter"] in html
    for topic in card["topics"]:
        assert f'id="{cards.slugify(topic)}"' in html
    assert '<span class="badge">Today</span>' in html


def test_chapter_page_shows_cached_summary(student, app):
    cache(app, "Physics: Coulomb's law", "Coulomb's law describes the force between charges.")
    html = student.get("/study/physics/electrostatics").data.decode()
    assert "Coulomb&#39;s law describes the force between charges." in html


@pytest.mark.parametrize("url", ("/study/physics/no-such-chapter", "/study/astrology/electrostatics"))
def test_unknown_chapter_is_404(student, url):
    assert student.get(url).status_code == 404


# Today page summaries


def test_today_shows_summaries_for_cards_and_followed_topics(student, app):
    card = todays_cards()[0]
    cache(app, f"{card['subject']}: {card['topic']}", "A short explanation of the topic.")
    pick = explore.todays_picks(
        ["science-tech", "sports"], explore.load_interest_topics(), date.today()
    )[1]
    cache(app, f"Sports: {pick['article']}", "A short explanation of the pick.")

    html = student.get("/").data.decode()
    assert "A short explanation of the topic." in html
    assert "A short explanation of the pick." in html
    assert "From your topics" in html
    assert pick["name"] in html


def test_today_without_summaries_still_works(student):
    html = student.get("/").data.decode()
    assert "From your topics" in html
    assert "No summary yet" in html


def test_pages_make_no_wikipedia_calls_when_live_is_off(student, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("tried to reach Wikipedia")

    monkeypatch.setattr(topic_info, "fetch_summary", boom)
    assert student.get("/").status_code == 200
    assert student.get("/topics/sports").status_code == 200
    assert student.get("/study/physics/electrostatics").status_code == 200


def test_today_fetches_and_caches_when_live(student, app, monkeypatch):
    app.config["TOPIC_INFO_LIVE"] = True
    calls = []

    def fake_fetch(search, get=None):
        calls.append(search["key"])
        return {"title": "T", "summary": f"About {search['query']}.", "url": "https://en.wikipedia.org/wiki/T"}

    monkeypatch.setattr(topic_info, "fetch_summary", fake_fetch)
    card = todays_cards()[0]
    html = student.get("/").data.decode()
    assert f"About {card['topic']}.".replace("'", "&#39;") in html
    count = len(calls)
    assert count == len(todays_cards()) + 2  # three cards + two followed topics
    student.get("/")
    assert len(calls) == count  # second visit served from the cache
