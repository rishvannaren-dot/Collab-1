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


def channel_mix_luminances(colours, steps=24):
    """Relative luminance of every blend of the given colours (any mix the browser may paint)."""
    rgbs = [[int(c[i : i + 2], 16) for i in (1, 3, 5)] for c in colours]
    found = []
    for i in range(steps + 1):
        for j in range(steps + 1 - i):
            weights = (i / steps, j / steps, 1 - (i + j) / steps)
            mix = [sum(w * rgb[k] for w, rgb in zip(weights, rgbs)) for k in range(3)]
            found.append(luminance("#" + "".join(f"{round(v):02x}" for v in mix)))
    return min(found), max(found)


@pytest.mark.parametrize("theme", ("light", "dark"))
def test_text_stays_readable_over_the_daylight(theme):
    """The two patches of light behind the page head, alone or overlapping, keep AA contrast."""
    light = tokens("\n:root")
    colours = light if theme == "light" else {**light, **tokens(':root[data-theme="dark"]')}
    darkest, lightest = channel_mix_luminances([colours["bg"], colours["glow-1"], colours["glow-2"]])
    failures = []
    for fg, floor in [(c, 4.5) for c in ("text", "text-2", "muted", "accent-text", "ok", "warn", "bad", "danger")] + [
        ("border-strong", 3),
        ("focus", 3),
    ]:
        fg_lum = luminance(colours[fg])
        worst = min((max(fg_lum, bg) + 0.05) / (min(fg_lum, bg) + 0.05) for bg in (darkest, lightest))
        if worst < floor:
            failures.append(f"{fg}: {worst:.2f}")
    assert not failures, failures


def test_system_dark_theme_matches_the_dark_toggle():
    system = re.search(r"prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme=\"light\"\]\)\s*\{(.*?)\n  \}", CSS, re.S)
    system_tokens = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", system.group(1)))
    assert system_tokens == tokens(':root[data-theme="dark"]')


def enclosing_blocks(css, position):
    """The selectors and at-rules wrapping a position in the stylesheet, outermost first."""
    stack, start = [], 0
    for match in re.finditer(r"[{};]", css[:position]):
        if match.group() == "{":
            stack.append(css[start : match.start()].strip())
        elif match.group() == "}" and stack:
            stack.pop()
        start = match.end()
    return stack


def test_motion_only_runs_for_people_who_have_not_asked_for_less():
    """Every animation, and page-to-page transitions, sit inside prefers-reduced-motion: no-preference."""
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    leaks = []
    for match in re.finditer(r"(?:animation(?:-name)?\s*:\s*([^;}]+))|@view-transition", css):
        if match.group(1) and match.group(1).strip().startswith("none"):
            continue
        blocks = enclosing_blocks(css, match.start())
        if not any("prefers-reduced-motion: no-preference" in b for b in blocks):
            leaks.append(f"{' > '.join(blocks) or '(top level)'}: {match.group(0)[:60]}")
    assert not leaks, leaks


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



def test_background_motion_stops_by_itself():
    """No endless animation, and no script-driven animation loop, so a long study session stays still."""
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    endless = [m.group(0) for m in re.finditer(r"animation[^;{}]*;", css) if "infinite" in m.group(0)]
    assert not endless, endless
    script = (Path(__file__).parent.parent / "focusfeed" / "static" / "app.js").read_text()
    assert "requestAnimationFrame" not in script and "setInterval" not in script


def test_page_transitions_never_add_the_two_pages_together():
    """Overriding the browser's crossfade must also drop its plus-lighter blend, or the screen flashes white."""
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    rules = re.findall(r"([^{}]*::view-transition-(?:old|new)\(root\)[^{}]*)\{([^{}]*)\}", css)
    overriding = [(sel.strip(), body) for sel, body in rules if re.search(r"animation\s*:", body)]
    assert overriding, "expected the page arrival transition"
    for selector, body in overriding:
        assert "mix-blend-mode: normal" in body, selector


def test_daylight_is_left_out_of_print_and_high_contrast():
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    contexts = [" ".join(enclosing_blocks(css, m.start())) for m in re.finditer(r"\.content::before", css)]
    assert any("@media print" in c for c in contexts)
    assert any("forced-colors: active" in c and "prefers-contrast: more" in c for c in contexts)
