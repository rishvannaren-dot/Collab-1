import re

from focusfeed.db import get_db
from focusfeed.services import preferences
from tests.helpers import csrf_token, make_student


def interests(app, user_id=1):
    with app.app_context():
        return preferences.get_preferences(get_db(), user_id)["interests"]


def test_explore_shows_only_the_students_syllabus(client):
    make_student(client)
    html = client.get("/explore").data.decode()
    chapters = set(re.findall(r'href="(/study/[^/"#]+/[^/"#]+)"', html))
    assert len(chapters) == 17  # 7 Physics + 5 Chemistry + 5 Maths, all Class 12
    assert "Kinematics" not in html  # Class 11
    assert "Biology" not in html and "/study/biology/" not in html
    for url in chapters:
        assert client.get(url).status_code == 200


def test_neet_shows_biology_not_maths(client):
    make_student(client, goal="neet")
    html = client.get("/explore").data.decode()
    assert "/study/biology/" in html
    assert "/study/maths/" not in html


def test_general_grade_9_sees_a_note_and_all_topics(client):
    make_student(client, grade=9, goal="general", interests=("sports",))
    html = client.get("/explore").data.decode()
    assert "Classes 11 and 12 for now" in html
    assert "/study/" not in html
    for key in preferences.INTERESTS:
        assert f'href="/topics/{key}"' in html


def test_this_week_badge_and_start_buttons(client):
    make_student(client)
    html = client.get("/explore").data.decode()
    assert html.count(">This week<") == 3  # one per subject
    assert 'action="/study/physics/current-electricity/start"' in html
    assert 'action="/study/physics/electrostatics/start"' not in html


def test_follow_and_unfollow(client, app):
    make_student(client)
    response = client.post("/topics/music/follow", data={"next": "/explore"})
    assert response.headers["Location"] == "/explore"
    assert "music" in interests(app)
    assert "Music" in client.get("/").data.decode()  # a Music pick on Today
    client.post("/topics/music/unfollow")
    assert "music" not in interests(app)


def test_cannot_unfollow_the_last_topic(client, app):
    make_student(client, interests=("sports",))
    client.post("/topics/sports/unfollow")
    assert interests(app) == ["sports"]
    assert "Follow at least one topic." in client.get("/explore").data.decode()


def test_follow_unknown_topic_is_404(client):
    make_student(client)
    assert client.post("/topics/astrology/follow").status_code == 404
    assert client.post("/topics/astrology/unfollow").status_code == 404


def test_explore_requires_login(client):
    assert client.get("/explore").headers["Location"].endswith("/welcome")
    assert client.post("/topics/music/follow").headers["Location"].endswith("/welcome")


def test_follow_without_csrf_token_changes_nothing(csrf_client):
    csrf_client.post(
        "/auth/register",
        data={"username": "alice", "password": "longenough1", "consent": "on", "csrf_token": csrf_token(csrf_client, "/auth/register")},
    )
    csrf_client.post(
        "/onboarding",
        data={"interests": ["sports"], "grade": "12", "goal": "jee", "csrf_token": csrf_token(csrf_client, "/onboarding")},
    )
    csrf_client.post("/topics/music/follow", data={"next": "/explore"})
    html = csrf_client.get("/explore").data.decode()
    assert 'aria-label="Follow Music"' in html  # still not followed


def test_search_hooks_are_on_the_page(client):
    make_student(client)
    html = client.get("/explore").data.decode()
    assert "data-topic-search" in html and "data-search-empty" in html
    assert 'data-topic="electrostatics coulomb&#39;s law' in html  # chapters are searchable by topic


def test_topic_page_has_follow_buttons(client):
    make_student(client)
    assert 'aria-label="Follow Music"' in client.get("/topics/music").data.decode()
    assert 'aria-label="Unfollow Sports"' in client.get("/topics/sports").data.decode()


def test_following_does_not_reset_the_plan(client, app):
    make_student(client)
    client.post("/study/physics/current-electricity/start")
    client.post("/topics/music/follow")
    assert "Current Electricity" in client.get("/").data.decode()


def test_today_cards_link_to_explore(client):
    make_student(client)
    assert 'href="/explore#physics"' in client.get("/").data.decode()
