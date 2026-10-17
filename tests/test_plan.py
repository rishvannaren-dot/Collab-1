import re
from datetime import date

import pytest

from focusfeed.db import get_db
from tests.helpers import csrf_token, make_student


def plan_rows(app):
    with app.app_context():
        rows = get_db().execute(
            "SELECT subject_key, chapter_index, start_on FROM study_plan ORDER BY subject_key"
        ).fetchall()
    return [tuple(r) for r in rows]


def test_onboarding_starts_every_subject_at_chapter_one_today(client, app):
    make_student(client)
    assert plan_rows(app) == [
        ("chemistry", 0, "2026-10-20"),
        ("maths", 0, "2026-10-20"),
        ("physics", 0, "2026-10-20"),
    ]


def test_changing_only_interests_keeps_the_plan(client, app, clock_at):
    make_student(client)
    clock_at(date(2026, 10, 22))
    client.post("/onboarding", data={"interests": ["music"], "grade": "12", "goal": "jee"})
    assert all(start == "2026-10-20" for _, _, start in plan_rows(app))


def test_changing_grade_or_goal_restarts_the_plan(client, app, clock_at):
    make_student(client)
    clock_at(date(2026, 10, 22))
    client.post("/onboarding", data={"interests": ["sports"], "grade": "12", "goal": "neet"})
    assert plan_rows(app) == [
        ("biology", 0, "2026-10-22"),
        ("chemistry", 0, "2026-10-22"),
        ("physics", 0, "2026-10-22"),
    ]
    client.post("/onboarding", data={"interests": ["sports"], "grade": "9", "goal": "general"})
    assert plan_rows(app) == []


def test_day_one_is_the_chapters_first_topic(client):
    make_student(client)
    html = client.get("/").data.decode()
    assert "Electrostatics" in html
    assert "Day 1 of 7" in html
    assert "Coulomb&#39;s law" in html


def test_study_this_chapter_this_week(client, clock_at):
    make_student(client)
    clock_at(date(2026, 10, 23))
    response = client.post("/study/physics/current-electricity/start")
    assert response.headers["Location"] == "/"
    html = client.get("/").data.decode()
    assert "is this week&#39;s chapter" in html  # flash
    card = html[html.index('id="card-physics"'):html.index('id="card-chemistry"')]
    assert "Current Electricity" in card and "Day 1 of 7" in card
    assert "Ohm&#39;s law and resistivity" in card
    assert "Day 4 of 7" in html  # chemistry carries on from Tuesday


@pytest.mark.parametrize(
    "url",
    (
        "/study/physics/kinematics/start",  # a Class 11 chapter for a Class 12 student
        "/study/biology/biomolecules/start",  # not a JEE subject
        "/study/physics/no-such-chapter/start",
    ),
)
def test_start_rejects_chapters_outside_the_students_plan(client, url):
    make_student(client)
    assert client.post(url).status_code == 404


def test_start_requires_login(client):
    assert client.post("/study/physics/electrostatics/start").headers["Location"].endswith("/welcome")


def test_start_without_csrf_token_changes_nothing(csrf_client, app):
    csrf_client.post(
        "/auth/register",
        data={
            "username": "alice",
            "password": "longenough1",
            "consent": "on",
            "csrf_token": csrf_token(csrf_client, "/auth/register"),
        },
    )
    csrf_client.post(
        "/onboarding",
        data={
            "interests": ["sports"],
            "grade": "12",
            "goal": "jee",
            "csrf_token": csrf_token(csrf_client, "/onboarding"),
        },
    )
    csrf_client.post("/study/physics/current-electricity/start", data={"next": "/"})
    html = csrf_client.get("/").data.decode()
    assert "Electrostatics" in html and "Current Electricity" not in html


def test_review_and_rest_days(client, clock_at):
    make_student(client)
    clock_at(date(2026, 10, 25))  # day 6: Electrostatics has 5 topics, so this is review
    html = client.get("/").data.decode()
    assert "Chapter review" in html
    assert "Close the book." in html
    assert client.get("/videos").status_code == 200

    clock_at(date(2026, 10, 26))  # day 7
    html = client.get("/").data.decode()
    assert "Rest day" in html
    assert client.get("/videos").status_code == 200


def test_practice_day_for_a_four_topic_chapter(client, clock_at):
    make_student(client)
    client.post("/study/physics/current-electricity/start")  # 4 topics
    clock_at(date(2026, 10, 25))  # day 6
    assert "Practice day" in client.get("/").data.decode()


def test_video_links_on_today_match_sections_on_videos(client):
    make_student(client)
    today = client.get("/").data.decode()
    videos = client.get("/videos").data.decode()
    anchors = re.findall(r'href="/videos#([^"]+)"', today)
    assert anchors
    for anchor in anchors:
        assert f'id="{anchor}"' in videos


def test_chapter_page_shows_this_week_or_offers_to_start(client):
    make_student(client)
    current = client.get("/study/physics/electrostatics").data.decode()
    assert "This week's chapter · Day 1 of 7" in current
    other = client.get("/study/physics/current-electricity").data.decode()
    assert "Study this chapter this week" in other
    grade_11 = client.get("/study/physics/kinematics").data.decode()
    assert "Study this chapter this week" not in grade_11
