import re
from datetime import date, timedelta

import pytest

from focusfeed.db import get_db
from focusfeed.services import progress, revision, topic_info
from tests.helpers import csrf_token, make_student

D = date(2026, 10, 20)
COULOMB = "physics/electrostatics/coulomb-s-law"


# The schedule


def test_schedule_first():
    assert revision.schedule_first(3, D) == (1, D + timedelta(days=3))
    assert revision.schedule_first(2, D) == (0, D + timedelta(days=1))
    assert revision.schedule_first(1, D) == (0, D + timedelta(days=1))


def test_after_review_grows_then_caps():
    box, gaps = 1, []
    for _ in range(5):
        box, due = revision.after_review(box, True, D)
        gaps.append((box, (due - D).days))
    assert gaps == [(2, 7), (3, 14), (4, 30), (5, 60), (5, 60)]
    assert revision.after_review(4, False, D) == (0, D + timedelta(days=1))


def seed(db, user_id, key, due_on, box=1, confidence=3):
    db.execute(
        "INSERT INTO topic_progress (user_id, topic_key, confidence, first_studied_on, last_studied_on, box, due_on)"
        " VALUES (?, ?, ?, '2026-10-01', '2026-10-01', ?, ?)",
        (user_id, key, confidence, box, due_on),
    )
    db.commit()


@pytest.fixture
def db_user(app):
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO users (username, password_hash) VALUES ('a', 'x')")
        db.commit()
        yield db


def test_due_orders_limits_and_filters(db_user):
    keys = [f"physics/electrostatics/t{i}" for i in range(7)]
    for i, key in enumerate(keys):
        seed(db_user, 1, key, f"2026-10-{10 + i:02d}")
    seed(db_user, 1, "physics/electrostatics/future", "2026-10-30")
    seed(db_user, 1, "maths/integrals/substitution", "2026-10-01")  # not allowed
    items, more = revision.due(db_user, 1, D, set(keys) | {"physics/electrostatics/future"})
    assert [i["topic_key"] for i in items] == keys[:5]
    assert more is True


def test_forgetting_lowers_confidence_and_comes_back_tomorrow(db_user):
    seed(db_user, 1, COULOMB, "2026-10-20", box=3, confidence=3)
    assert revision.record_review(db_user, 1, COULOMB, False, D)
    row = progress.progress_for(db_user, 1)[COULOMB]
    assert (row["box"], row["due_on"], row["confidence"]) == (0, "2026-10-21", 2)
    assert not revision.record_review(db_user, 1, "physics/x/y", True, D)


def test_recall_prompts():
    for subject in ("physics", "chemistry", "maths", "biology"):
        templates = revision.RECALL_PROMPTS[subject]
        assert len(templates) >= 2 and all("{topic}" in t for t in templates)
    a = revision.recall_prompt("physics", "Gauss's law", D)
    assert a == revision.recall_prompt("physics", "Gauss's law", D)
    assert "Gauss's law" in a
    assert a != revision.recall_prompt("physics", "Gauss's law", D + timedelta(days=1))


# Revise today on the Today page


def mark(client, key=COULOMB, confidence="3"):
    client.post("/study/mark", data={"topic_key": key, "confidence": confidence, "next": "/"})


def review(client, remembered, key=COULOMB):
    return client.post("/study/review", data={"topic_key": key, "remembered": remembered, "next": "/#revise"})


def due_row(app, key=COULOMB):
    with app.app_context():
        return dict(get_db().execute("SELECT * FROM topic_progress WHERE topic_key = ?", (key,)).fetchone())


def test_a_got_it_topic_comes_back_after_three_days(client, clock_at):
    make_student(client)
    mark(client)
    clock_at(date(2026, 10, 22))
    assert "Revise today" not in client.get("/").data.decode()
    clock_at(date(2026, 10, 23))
    html = client.get("/").data.decode()
    revise = html[html.index("Revise today"):]
    assert "Coulomb&#39;s law" in revise
    assert "Write the law or formula" in revise or "Explain Coulomb" in revise


def test_remembering_and_forgetting(client, app, clock_at):
    make_student(client)
    mark(client)
    clock_at(date(2026, 10, 23))
    assert review(client, "1").headers["Location"] == "/#revise"
    row = due_row(app)
    assert (row["box"], row["due_on"]) == (2, "2026-10-30")
    clock_at(date(2026, 10, 30))
    review(client, "0")
    row = due_row(app)
    assert (row["box"], row["due_on"], row["confidence"]) == (0, "2026-10-31", 2)


def test_a_double_tap_counts_once(client, app, clock_at):
    make_student(client)
    mark(client)
    clock_at(date(2026, 10, 23))
    review(client, "1")
    review(client, "1")
    row = due_row(app)
    assert (row["box"], row["due_on"]) == (2, "2026-10-30")


def test_reviewing_before_it_is_due_changes_nothing(client, app):
    make_student(client)
    mark(client)
    before = due_row(app)
    assert review(client, "1").headers["Location"] == "/#revise"
    assert due_row(app) == before


def test_remembering_raises_confidence(client, app, clock_at):
    make_student(client)
    mark(client, confidence="1")  # Lost me, due tomorrow
    clock_at(date(2026, 10, 21))
    review(client, "1")
    assert due_row(app)["confidence"] == 2
    clock_at(date(2026, 10, 24))
    review(client, "1")
    assert due_row(app)["confidence"] == 3
    assert 'id="needs-work"' not in client.get("/progress").data.decode()


def test_review_only_for_your_own_studied_topics(client, app):
    make_student(client)
    assert review(client, "1").status_code == 404
    other = app.test_client()
    make_student(other, "bob")
    mark(other)
    assert review(client, "1").status_code == 404
    assert review(client, "maybe").status_code == 400


def test_review_without_csrf_token_changes_nothing(csrf_client):
    csrf_client.post(
        "/auth/register",
        data={"username": "alice", "password": "longenough1", "consent": "on", "csrf_token": csrf_token(csrf_client, "/auth/register")},
    )
    response = csrf_client.post("/study/review", data={"topic_key": COULOMB, "remembered": "1", "next": "/#revise"})
    assert response.headers["Location"] == "/#revise"


def test_at_most_five_and_no_backlog_number(client, app, clock_at):
    make_student(client)
    keys = [
        "physics/electrostatics/coulomb-s-law",
        "physics/electrostatics/gauss-s-law",
        "physics/electrostatics/electric-potential",
        "physics/current-electricity/kirchhoff-s-laws",
        "physics/current-electricity/wheatstone-bridge",
        "chemistry/solutions/raoult-s-law",
        "maths/integrals/substitution",
    ]
    for key in keys:
        mark(client, key)
    clock_at(date(2026, 10, 30))
    html = client.get("/").data.decode()
    revise = html[html.index('id="revise"'):html.index("From your topics")]
    assert revise.count('name="remembered" value="1"') == 5
    assert "More come back on later days." in revise
    text = re.sub(r"<[^>]+>", " ", revise)
    assert not re.search(r"\b\d+\s+(more|left|waiting|overdue|due)\b", text, re.I)  # no backlog count


def test_revise_summaries_come_from_the_cache_only(client, app, clock_at, monkeypatch):
    make_student(client)
    mark(client)
    app.config["TOPIC_INFO_LIVE"] = True
    calls = []

    def fake_fetch(search, get=None):
        calls.append(search["key"])
        return None

    monkeypatch.setattr(topic_info, "fetch_summary", fake_fetch)
    clock_at(date(2026, 10, 23))  # day 4: Coulomb is due, three learn cards are live
    client.get("/")
    assert "Physics: Coulomb's law" not in calls


def test_old_revise_line_is_gone(client, clock_at):
    make_student(client)
    clock_at(date(2026, 10, 27))  # a week later: the plan has been through Electrostatics
    assert "Revise:" not in client.get("/").data.decode()


def test_review_day_shows_recall_prompts(client, clock_at):
    make_student(client)
    clock_at(date(2026, 10, 25))
    html = client.get("/").data.decode()
    assert "Chapter review" in html
    assert "Coulomb&#39;s law" in html
    assert "Close the book. Write the law or formula for each topic" in html or "Close the book. Explain each topic" in html
    assert html.count("for each topic") + html.count("Explain each topic") == 1  # said once, not per topic


def test_chapter_page_shows_next_review(client):
    make_student(client)
    mark(client)
    assert "next review 23 Oct 2026" in client.get("/study/physics/electrostatics").data.decode()
