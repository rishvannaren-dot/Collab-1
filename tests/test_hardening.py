import re
from pathlib import Path

import pytest

from focusfeed import debug_enabled
from tests.conftest import make_app
from tests.helpers import login, make_student, register
from tests.test_accessibility import PUBLIC_PAGES, student_pages

STATIC = Path(__file__).parent.parent / "focusfeed" / "static"


def test_security_headers_on_public_and_private_pages(client):
    for response in (client.get("/welcome"), None):
        if response is None:
            make_student(client)
            response = client.get("/")
        csp = response.headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
        assert "script-src 'self' 'nonce-" in csp
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Referrer-Policy"] == "same-origin"
        assert response.headers["X-Frame-Options"] == "DENY"


def test_inline_script_carries_the_nonce_and_it_changes(client):
    nonces = []
    for _ in range(2):
        response = client.get("/welcome")
        header = re.search(r"'nonce-([^']+)'", response.headers["Content-Security-Policy"]).group(1)
        assert f'<script nonce="{header}">' in response.data.decode()
        nonces.append(header)
    assert nonces[0] != nonces[1]


def test_private_pages_are_not_cached(client):
    make_student(client)
    assert client.get("/").headers["Cache-Control"] == "no-store"
    assert client.get("/static/style.css").headers.get("Cache-Control") != "no-store"
    client.post("/auth/logout")
    assert client.get("/welcome").headers.get("Cache-Control") != "no-store"


def page_problems(url, html):
    problems = []
    for script in re.findall(r"<script\b[^>]*>", html):
        if "src=" not in script and "nonce=" not in script:
            problems.append(f"inline script without nonce: {script}")
    if re.search(r"\sstyle=\"", html):
        problems.append("style= attribute")
    if re.search(r"\son[a-z]+=", html):
        problems.append("on*= event attribute")
    if "fonts.googleapis.com" in html or "fonts.gstatic.com" in html:
        problems.append("Google Fonts")
    return [f"{url}: {p}" for p in problems]


def test_no_page_breaks_the_content_security_policy(client):
    problems = []
    for url in PUBLIC_PAGES:
        problems += page_problems(url, client.get(url).data.decode())
    make_student(client)
    client.post("/study/mark", data={"topic_key": "physics/electrostatics/coulomb-s-law", "confidence": "2", "next": "/"})
    for url in student_pages():
        problems += page_problems(url, client.get(url).data.decode())
    assert not problems, problems


def test_fonts_are_served_locally_with_their_licence(client):
    css = (STATIC / "style.css").read_text()
    urls = re.findall(r'url\("(fonts/[^"]+)"\)', css)
    assert len(urls) == 5
    for url in urls:
        response = client.get(f"/static/{url}")
        assert response.status_code == 200
        assert response.data[:4] == b"wOF2"
    for licence in ("OFL-dm-sans.txt", "OFL-newsreader.txt"):
        assert "SIL Open Font License" in (STATIC / "fonts" / licence).read_text()


def test_one_inline_script_and_it_carries_the_nonce(client):
    response = client.get("/welcome")
    html = response.data.decode()
    nonce = re.search(r"'nonce-([^']+)'", response.headers["Content-Security-Policy"]).group(1)
    inline = [tag for tag in re.findall(r"<script\b[^>]*>", html) if "src=" not in tag]
    assert inline == [f'<script nonce="{nonce}">']
    assert not re.search(r"\sstyle=\"", html)


def test_preloaded_fonts_exist_and_are_used(client):
    css = (STATIC / "style.css").read_text()
    html = client.get("/welcome").data.decode()
    preloads = re.findall(r'<link rel="preload" href="/static/(fonts/[^"]+)" as="font" type="font/woff2" crossorigin>', html)
    assert len(preloads) == 2
    for path in preloads:
        assert f'url("{path}")' in css
        assert client.get(f"/static/{path}").status_code == 200


def test_secure_cookie_setting(tmp_path, monkeypatch):
    app = make_app(tmp_path, SESSION_COOKIE_SECURE=True)
    client = app.test_client()
    register(client)
    client.post("/auth/logout")
    assert "Secure" in login(client).headers["Set-Cookie"]

    monkeypatch.setenv("FOCUSFEED_HTTPS", "1")
    assert make_app(tmp_path).config["SESSION_COOKIE_SECURE"] is True
    monkeypatch.delenv("FOCUSFEED_HTTPS")
    assert make_app(tmp_path).config["SESSION_COOKIE_SECURE"] is False


def test_trust_proxy_is_opt_in(tmp_path, monkeypatch):
    assert type(make_app(tmp_path).wsgi_app).__name__ != "ProxyFix"
    monkeypatch.setenv("TRUST_PROXY", "1")
    assert type(make_app(tmp_path).wsgi_app).__name__ == "ProxyFix"


def test_oversized_posts_get_a_friendly_page(client):
    response = client.post("/auth/login", data={"username": "x" * 100_000, "password": "y"})
    assert response.status_code == 413
    assert b"too big to send" in response.data


def test_empty_login_post_is_a_normal_error(client):
    response = client.post("/auth/login", data={})
    assert response.status_code == 200
    assert b"Incorrect username or password." in response.data


def test_wrong_method_gets_a_friendly_page(client):
    response = client.get("/auth/logout")
    assert response.status_code == 405
    assert b"That didn" in response.data


def test_server_errors_get_a_friendly_page(tmp_path):
    app = make_app(tmp_path, PROPAGATE_EXCEPTIONS=False)

    def boom():
        raise RuntimeError("test failure")

    app.add_url_rule("/boom", "boom", boom)
    response = app.test_client().get("/boom")
    assert response.status_code == 500
    assert b"Something went wrong" in response.data
    assert b"test failure" not in response.data


@pytest.mark.parametrize(("environ", "expected"), (({}, False), ({"FLASK_DEBUG": "1"}, True), ({"FLASK_DEBUG": "0"}, False)))
def test_debug_is_off_unless_asked_for(environ, expected):
    assert debug_enabled(environ) is expected
