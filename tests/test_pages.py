import re

import pytest


@pytest.fixture
def student(client):
    client.post(
        "/auth/register",
        data={"username": "alice", "password": "longenough1", "consent": "on"},
    )
    client.post("/auth/login", data={"username": "alice", "password": "longenough1"})
    client.post(
        "/onboarding",
        data={"interests": ["science-tech", "education"], "grade": "12", "goal": "jee"},
    )
    return client


def test_home_shows_study_cards(student):
    html = student.get("/").data.decode()
    assert "Physics" in html and "Chemistry" in html and "Maths" in html
    assert "Watch videos" in html


def test_home_for_general_goal_shows_message(client):
    client.post(
        "/auth/register",
        data={"username": "bob", "password": "longenough1", "consent": "on"},
    )
    client.post("/auth/login", data={"username": "bob", "password": "longenough1"})
    client.post("/onboarding", data={"interests": ["sports"], "grade": "9", "goal": "general"})
    html = client.get("/").data.decode()
    assert "Study cards are built for" in html


def test_videos_page_without_api_key(student):
    response = student.get("/videos")
    assert response.status_code == 200
    html = response.data.decode()
    assert "Live YouTube search is off" in html
    assert "Search YouTube for this topic" in html
    assert "youtube.com/results?search_query=" in html


def test_videos_requires_login(client):
    response = client.get("/videos")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/welcome")


def test_videos_redirects_to_onboarding_without_preferences(client):
    client.post(
        "/auth/register",
        data={"username": "carol", "password": "longenough1", "consent": "on"},
    )
    client.post("/auth/login", data={"username": "carol", "password": "longenough1"})
    assert client.get("/videos").headers["Location"].endswith("/onboarding")


def test_privacy_page_is_public(client):
    assert client.get("/privacy").status_code == 200


def test_404_page(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert b"Page not found" in response.data


def test_welcome_is_public(client):
    response = client.get("/welcome")
    assert response.status_code == 200
    assert b"Get started" in response.data
    assert b"I already have an account" in response.data


def test_welcome_redirects_when_logged_in(student):
    response = student.get("/welcome")
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_home_has_greeting_and_nav(student):
    html = student.get("/").data.decode()
    assert "alice" in html
    assert "data-greeting" in html
    assert "Today&#39;s focus" in html or "Today's focus" in html
    assert 'class="tabbar"' in html
    assert "Followed topics" in html
    assert "Science &amp; Technology" in html
    assert "data-theme-toggle" in html


def test_topic_picker_has_search_and_icons(student):
    html = student.get("/onboarding").data.decode()
    assert "data-topic-search" in html
    assert html.count('class="topic"') == 8


# Navigation


def tab_links(html):
    bar = html[html.index('class="tabbar"'):]
    bar = bar[: bar.index("</nav>")]
    return re.findall(r'<a class="tab[^"]*" href="([^"]+)"', bar), bar


def test_tab_bar_has_five_sections(student):
    hrefs, bar = tab_links(student.get("/").data.decode())
    assert hrefs == ["/", "/explore", "/videos", "/progress", "/account"]
    assert 'class="tab active" href="/" aria-current="page"' in bar


def test_sidebar_has_explore_and_progress(student):
    html = student.get("/").data.decode()
    side = html[html.index('class="side-nav"'):html.index('class="followed"')]
    assert 'href="/explore"' in side and 'href="/progress"' in side


@pytest.mark.parametrize(
    ("url", "current"),
    (
        ("/study/physics/electrostatics", "/explore"),
        ("/topics/sports", "/explore"),
        ("/progress", "/progress"),
        ("/onboarding", "/account"),
        ("/account/password", "/account"),
    ),
)
def test_the_right_tab_is_current(student, url, current):
    _, bar = tab_links(student.get(url).data.decode())
    assert re.findall(r'href="([^"]+)" aria-current="page"', bar) == [current]


def test_me_page_links_to_preferences(student):
    html = student.get("/account").data.decode()
    assert 'href="/onboarding"' in html
    assert "Grade 12" in html and "Science &amp; Technology" in html


def test_chapter_breadcrumb_and_pager(student):
    html = student.get("/study/physics/electrostatics").data.decode()
    assert 'href="/explore#physics"' in html
    assert "Previous chapter" not in html  # first Class 12 Physics chapter
    links = re.findall(r'class="pager-link[^"]*" href="([^"]+)"', html)
    assert links == ["/study/physics/current-electricity"]
    middle = student.get("/study/physics/current-electricity").data.decode()
    links = re.findall(r'class="pager-link[^"]*" href="([^"]+)"', middle)
    assert links == ["/study/physics/electrostatics", "/study/physics/magnetic-effects-of-current"]
    for link in links:
        assert student.get(link).status_code == 200
