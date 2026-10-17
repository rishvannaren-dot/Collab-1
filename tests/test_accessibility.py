"""Automatic accessibility checks over every page, plus colour contrast of the theme tokens."""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from focusfeed.services import cards, preferences
from tests.helpers import make_student

NEW_TAB_TEXT = "(opens in a new tab)"
CSS = (Path(__file__).parent.parent / "focusfeed" / "static" / "style.css").read_text()


class PageAudit(HTMLParser):
    """Collects the facts the checks below need from one HTML page."""

    def __init__(self):
        super().__init__()
        self.h1 = 0
        self.ids = []
        self.label_for = set()
        self.label_depth = 0
        self.fields = []  # (tag, id, has_label_or_aria)
        self.images_without_alt = []
        self.open = []  # [tag, attrs, text] for open <a> and <button> elements
        self.unnamed = []
        self.new_tab_without_text = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "h1":
            self.h1 += 1
        elif tag == "label":
            self.label_depth += 1
            if "for" in a:
                self.label_for.add(a["for"])
        elif tag in ("input", "select", "textarea"):
            if a.get("type") != "hidden":
                self.fields.append((tag, a.get("id"), self.label_depth > 0 or "aria-label" in a, a.get("name")))
        elif tag == "img" and "alt" not in a:
            self.images_without_alt.append(a.get("src"))
        if tag in ("a", "button"):
            self.open.append([tag, a, ""])

    def handle_endtag(self, tag):
        if tag == "label":
            self.label_depth -= 1
        if tag in ("a", "button") and self.open and self.open[-1][0] == tag:
            tag, attrs, text = self.open.pop()
            if not text.strip() and not attrs.get("aria-label"):
                self.unnamed.append((tag, attrs.get("href") or attrs.get("class")))
            if attrs.get("target") == "_blank" and NEW_TAB_TEXT not in text:
                self.new_tab_without_text.append(attrs.get("href"))

    def handle_data(self, data):
        for frame in self.open:
            frame[2] += data


def audit(html):
    page = PageAudit()
    page.feed(html)
    return page


def check(url, html):
    page = audit(html)
    problems = []
    if page.h1 != 1:
        problems.append(f"{page.h1} <h1> elements")
    dupes = {i for i in page.ids if page.ids.count(i) > 1}
    if dupes:
        problems.append(f"duplicate ids {sorted(dupes)}")
    for tag, field_id, labelled, name in page.fields:
        if not labelled and field_id not in page.label_for:
            problems.append(f"unlabelled {tag} {field_id or name}")
    if page.images_without_alt:
        problems.append(f"images without alt {page.images_without_alt}")
    if page.unnamed:
        problems.append(f"links/buttons without a name {page.unnamed}")
    if page.new_tab_without_text:
        problems.append(f"new-tab links without notice {page.new_tab_without_text}")
    assert not problems, f"{url}: " + "; ".join(problems)


PUBLIC_PAGES = ["/welcome", "/auth/login", "/auth/register", "/auth/forgot", "/privacy"]


def student_pages():
    syllabus = cards.load_syllabus()
    pages = [
        "/",
        "/videos",
        "/onboarding",
        "/explore",
        "/progress",
        "/account",
        "/account/password",
        "/account/recovery-key",
        "/account/delete",
    ]
    pages += [f"/topics/{key}" for key in preferences.INTERESTS]
    pages += [
        f"/study/{key}/{cards.slugify(c['name'])}"
        for key, subject in syllabus["subjects"].items()
        for c in subject["chapters"]
    ]
    return pages


@pytest.mark.parametrize("url", PUBLIC_PAGES)
def test_public_pages(client, url):
    response = client.get(url)
    assert response.status_code == 200
    check(url, response.data.decode())


def test_not_found_page(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404
    check("/no-such-page", response.data.decode())


def test_every_student_page(client):
    make_student(client)
    client.post("/study/mark", data={"topic_key": "physics/electrostatics/coulomb-s-law", "confidence": "2", "next": "/"})
    for url in student_pages():
        response = client.get(url)
        assert response.status_code == 200, url
        check(url, response.data.decode())


def test_recovery_key_page(client):
    make_student(client)
    response = client.post("/account/recovery-key", data={"current": "longenough1"})
    check("recovery key", response.data.decode())


# Colour contrast


def tokens(selector):
    match = re.search(re.escape(selector) + r"\s*\{(.*?)\n\}", CSS, re.S)
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", match.group(1)))


def luminance(hex_colour):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


TEXT_PAIRS = [
    ("text", "bg"), ("text", "surface"), ("text-2", "bg"), ("text-2", "surface"), ("text-2", "subtle"),
    ("muted", "bg"), ("muted", "surface"), ("muted", "subtle"),
    ("accent-text", "bg"), ("accent-text", "surface"), ("accent-text", "accent-soft"), ("accent-ink", "accent"),
    ("text", "success-bg"), ("text", "danger-bg"), ("text", "notice-bg"),
    ("danger-ink", "danger"), ("danger", "surface"), ("danger", "danger-bg"),
    ("ok", "surface"), ("warn", "surface"), ("bad", "surface"), ("ok", "bg"), ("warn", "bg"), ("bad", "bg"),
    ("ok-ink", "ok"), ("text-2", "notice-bg"), ("muted", "notice-bg"),
]

# Borders that mark an input or a stop on the week line, and the focus ring, need 3:1 (WCAG 1.4.11).
NON_TEXT_PAIRS = [
    ("border-strong", "bg"), ("border-strong", "surface"), ("focus", "bg"), ("focus", "surface"),
    ("ok", "surface"), ("accent-text", "accent-soft"),
]


@pytest.mark.parametrize("theme", ("light", "dark"))
def test_text_colours_meet_wcag_aa(theme):
    light = tokens("\n:root")
    colours = light if theme == "light" else {**light, **tokens(':root[data-theme="dark"]')}
    failures = [
        f"{fg} on {bg}: {contrast(colours[fg], colours[bg]):.2f}"
        for fg, bg in TEXT_PAIRS
        if contrast(colours[fg], colours[bg]) < 4.5
    ]
    assert not failures, failures


@pytest.mark.parametrize("theme", ("light", "dark"))
def test_borders_and_focus_ring_meet_3_to_1(theme):
    light = tokens("\n:root")
    colours = light if theme == "light" else {**light, **tokens(':root[data-theme="dark"]')}
    failures = [
        f"{fg} on {bg}: {contrast(colours[fg], colours[bg]):.2f}"
        for fg, bg in NON_TEXT_PAIRS
        if contrast(colours[fg], colours[bg]) < 3
    ]
    assert not failures, failures


def test_system_dark_theme_matches_the_dark_toggle():
    system = re.search(r"prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme=\"light\"\]\)\s*\{(.*?)\n  \}", CSS, re.S)
    system_tokens = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", system.group(1)))
    assert system_tokens == tokens(':root[data-theme="dark"]')


@pytest.mark.parametrize(
    ("html", "problem"),
    (
        ("<h1>a</h1><h1>b</h1>", "2 <h1>"),
        ("<h1>a</h1><p id='x'></p><p id='x'></p>", "duplicate ids"),
        ("<h1>a</h1><input id='q' name='q'>", "unlabelled input"),
        ("<h1>a</h1><img src='x.png'>", "images without alt"),
        ("<h1>a</h1><button><svg></svg></button>", "without a name"),
        ("<h1>a</h1><a href='https://x.org' target='_blank'>X</a>", "new-tab links"),
    ),
)
def test_the_audit_catches_problems(html, problem):
    """The checks above must fail on broken pages, or passing them means nothing."""
    with pytest.raises(AssertionError, match=re.escape(problem)):
        check("example", html)


def test_the_audit_accepts_good_markup():
    check(
        "example",
        "<h1>a</h1><label for='q'>Q</label><input id='q'><label><input type='checkbox'> B</label>"
        "<input type='hidden' name='t'><img src='x' alt=''><button aria-label='Close'><svg></svg></button>"
        "<a href='https://x.org' target='_blank'>X<span class='sr-only'> (opens in a new tab)</span></a>",
    )
