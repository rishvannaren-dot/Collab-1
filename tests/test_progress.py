from datetime import date

import pytest

from focusfeed.db import get_db
from focusfeed.services import cards, progress
from tests.helpers import csrf_token, make_student

COULOMB = "physics/electrostatics/coulomb-s-law"


def mark(client, key=COULOMB, confidence="2", next="/#card-physics"):
    return client.post("/study/mark", data={"topic_key": key, "confidence": confidence, "next": next})


def rows(app):
    with app.app_context():
        return [dict(r) for r in get_db().execute("SELECT * FROM topic_progress")]


# The service


def test_topic_keys():
    assert progress.topic_key("physics", "Electrostatics", "Coulomb's law") == COULOMB
    index = progress.topic_index(cards.load_syllabus())
    total = sum(len(c["topics"]) for s in cards.load_syllabus()["subjects"].values() for c in s["chapters"])
    assert len(index) == total  # every topic has its own key
    assert progress.valid_key(cards.load_syllabus(), COULOMB)
    assert not progress.valid_key(cards.load_syllabus(), "physics/x/y")


def test_marking_twice_keeps_one_row_and_the_first_date(app):
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO users (username, password_hash) VALUES ('a', 'x')")
        progress.mark(db, 1, COULOMB, 1, date(2026, 10, 20))
        progress.mark(db, 1, COULOMB, 3, date(2026, 10, 20))
        progress.mark(db, 1, COULOMB, 2, date(2026, 10, 22))
        row = progress.progress_for(db, 1)[COULOMB]
        assert (row["confidence"], row["first_studied_on"], row["last_studied_on"]) == (2, "2026-10-20", "2026-10-22")
        progress.unmark(db, 1, COULOMB)
        assert progress.progress_for(db, 1) == {}


FAKE = {
    "subjects": {
        "physics": {
            "label": "Physics",
            "chapters": [
                {"name": "One", "grade": 12, "topics": ["A", "B"]},
                {"name": "Two", "grade": 12, "topics": ["C"]},
                {"name": "Old", "grade": 11, "topics": ["D"]},
            ],
        },
        "maths": {"label": "Maths", "chapters": [{"name": "M", "grade": 12, "topics": ["E"]}]},
    }
}


def row(confidence, last="2026-10-20"):
    return {"confidence": confidence, "last_studied_on": last}


def test_coverage_counts_and_ignores_orphans():
    studied = {"physics/one/a": row(3), "physics/two/c": row(1), "physics/gone/z": row(3)}
    result = progress.coverage(FAKE, ["physics"], 12, studied)
    assert len(result) == 1
    physics = result[0]
    assert (physics["done"], physics["total"]) == (2, 3)
    assert [(c["name"], c["done"], c["total"]) for c in physics["chapters"]] == [("One", 1, 2), ("Two", 1, 1)]


def test_needs_work():
    studied = {
        "physics/one/a": row(2, "2026-10-19"),
        "physics/one/b": row(1, "2026-10-20"),
        "physics/two/c": row(3),
        "maths/m/e": row(1),
    }
    items = progress.needs_work(FAKE, studied, ["physics"], 12)
    assert [i["topic"] for i in items] == ["B", "A"]  # Lost me first, then Shaky


def test_day_finished():
    cards_ = [
        {"kind": "learn", "topic_key": "k1"},
        {"kind": "learn", "topic_key": "k2"},
        {"kind": "rest"},
    ]
    today = date(2026, 10, 20)
    assert not progress.day_finished(cards_, {"k1": {"last_studied_on": "2026-10-20"}}, today)
    both = {"k1": {"last_studied_on": "2026-10-20"}, "k2": {"last_studied_on": "2026-10-20"}}
    assert progress.day_finished(cards_, both, today)
    assert not progress.day_finished([{"kind": "rest"}], {}, today)


def test_every_syllabus_topic_has_a_resolvable_key():
    syllabus = cards.load_syllabus()
    index = progress.topic_index(syllabus)
    for key, info in index.items():
        assert key == progress.topic_key(info["subject_key"], info["chapter"], info["topic"])


# Routes


def test_marking_from_today(client, app):
    make_student(client)
    response = mark(client)
    assert response.headers["Location"] == "/#card-physics"
    html = client.get("/").data.decode()
    assert "Studied today" in html
    assert "is-done" in html
    assert rows(app)[0]["confidence"] == 2
    chapter = client.get("/study/physics/electrostatics").data.decode()
    assert "1 of 5 topics studied" in chapter


@pytest.mark.parametrize(
    ("key", "confidence"),
    ((COULOMB, "0"), (COULOMB, "4"), (COULOMB, "x"), ("physics/x/y", "2"), ("", "2")),
)
def test_bad_marks_are_rejected(client, app, key, confidence):
    make_student(client)
    assert mark(client, key, confidence).status_code == 400
    assert rows(app) == []


@pytest.mark.parametrize("next_url", ("//evil.com", "https://evil.example", "javascript:alert(1)"))
def test_mark_never_redirects_off_site(client, next_url):
    make_student(client)
    assert mark(client, next=next_url).headers["Location"] == "/"


def test_undo(client, app):
    make_student(client)
    mark(client)
    client.post("/study/unmark", data={"topic_key": COULOMB, "next": "/"})
    assert rows(app) == []


def test_marking_requires_login(client):
    assert mark(client).headers["Location"].endswith("/welcome")
    assert client.get("/progress").headers["Location"].endswith("/welcome")


def test_marking_without_csrf_token_stores_nothing(csrf_client):
    csrf_client.post(
        "/auth/register",
        data={"username": "alice", "password": "longenough1", "consent": "on", "csrf_token": csrf_token(csrf_client, "/auth/register")},
    )
    csrf_client.post(
        "/onboarding",
        data={"interests": ["sports"], "grade": "12", "goal": "jee", "csrf_token": csrf_token(csrf_client, "/onboarding")},
    )
    response = mark(csrf_client)
    assert response.headers["Location"] == "/#card-physics"
    html = csrf_client.get("/").data.decode()
    assert "Electrostatics" in html and "Studied today" not in html


def test_another_student_sees_nothing(client, app):
    make_student(client)
    mark(client)
    other = app.test_client()
    make_student(other, "bob")
    assert "0 of 5 topics studied" in other.get("/study/physics/electrostatics").data.decode()


def test_finish_panel_after_every_learn_card(client):
    make_student(client)
    mark(client, COULOMB, "3")
    mark(client, "chemistry/solutions/raoult-s-law", "3")
    assert "That&#39;s everything for today" not in client.get("/").data.decode()
    mark(client, "maths/matrices-and-determinants/matrix-operations", "3")
    assert "That's everything for today" in client.get("/").data.decode()


def test_rest_day_lists_unmarked_topics(client, clock_at):
    make_student(client)
    mark(client, COULOMB)
    clock_at(date(2026, 10, 26))
    html = client.get("/").data.decode()
    physics = html[html.index('id="card-physics"'):html.index('id="card-chemistry"')]
    assert "Rest day" in physics
    assert "Gauss&#39;s law" in physics
    assert "Coulomb&#39;s law" not in physics.split("haven't marked yet")[1]


# The Progress page


def test_progress_page_empty_state(client):
    make_student(client)
    html = client.get("/progress").data.decode()
    assert "Mark a topic as studied" in html
    assert "Physics" in html and "Chemistry" in html and "Maths" in html
    assert "Biology" not in html


def test_progress_page_counts_and_needs_work(client):
    make_student(client)
    mark(client, COULOMB, "1")
    mark(client, "physics/electrostatics/gauss-s-law", "3")
    html = client.get("/progress").data.decode()
    assert "2 of 29 topics" in html
    needs = html[html.index("Needs work"):html.index('id="physics"')]
    assert "Coulomb&#39;s law" in needs
    assert "Gauss" not in needs


def test_progress_for_general_goal(client):
    make_student(client, grade=9, goal="general", interests=("sports",))
    assert "No study plan yet" in client.get("/progress").data.decode()
