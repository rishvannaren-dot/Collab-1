"""One- or two-line explanations of topics, looked up on Wikipedia and cached.

Google's web search API is closed to new projects, so this uses Wikipedia, which
is where most of Google's own topic summaries come from. No API key is needed.
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

API_URL = "https://en.wikipedia.org/w/api.php"
# Wikimedia asks every client to say who it is.
USER_AGENT = "FocusFeed/0.1 (student project; https://github.com/rishvannaren-dot/Collab-1)"

CACHE_TTL_SECONDS = 7 * 24 * 3600
MAX_LIVE_LOOKUPS = 12  # per page load; anything beyond waits for the next visit
MAX_WORKERS = 4
MAX_SENTENCES = 2
MAX_CHARS = 320

# Ask for the intro of one article as plain text, plus its URL and whether it
# is a disambiguation page ("X may refer to ...").
BASE_PARAMS = {
    "action": "query",
    "format": "json",
    "formatversion": "2",
    "prop": "extracts|info|pageprops",
    "exintro": "1",
    "explaintext": "1",
    "exsentences": "4",
    "inprop": "url",
    "ppprop": "disambiguation",
    "redirects": "1",
}


class InfoSourceError(Exception):
    """Wikipedia could not be reached or refused the request."""


def load_wiki_titles():
    with open(DATA_DIR / "wiki_titles.json", encoding="utf-8") as f:
        return json.load(f)["titles"]


def syllabus_search(topic, subject, titles):
    """How to look up a syllabus topic: its mapped article, else a search by name."""
    return {"key": f"{subject}: {topic}", "title": titles.get(topic), "query": topic, "context": subject}


def interest_search(article, label):
    """How to look up an interest topic, whose name is already an article title."""
    return {"key": f"{label}: {article}", "title": article, "query": article, "context": label}


_EMPTY_BRACKETS = re.compile(r"\s*\(\s*[;,]?\s*\)")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def short_summary(extract):
    """Return the first one or two sentences, stopping before any leftover math markup."""
    text = _EMPTY_BRACKETS.sub("", re.sub(r"\s+", " ", extract or "")).strip()
    sentences = []
    for sentence in _SENTENCE_END.split(text):
        if "\\displaystyle" in sentence or "{" in sentence:
            break
        if sentences and len(" ".join(sentences + [sentence])) > MAX_CHARS:
            break
        sentences.append(sentence)
        if len(sentences) == MAX_SENTENCES:
            break
    summary = " ".join(sentences)
    if len(summary) > MAX_CHARS:
        summary = summary[:MAX_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return summary


def _query(params, get):
    try:
        response = get(
            API_URL,
            params={**BASE_PARAMS, **params},
            headers={"User-Agent": USER_AGENT},
            timeout=5,
        )
    except requests.RequestException:
        raise InfoSourceError("Couldn't reach Wikipedia.")
    if response.status_code != 200:
        raise InfoSourceError(f"Wikipedia answered with status {response.status_code}.")
    try:
        pages = response.json().get("query", {}).get("pages", [])
    except ValueError:
        raise InfoSourceError("Wikipedia sent something unexpected.")
    if not pages:
        return None
    page = pages[0]
    if page.get("missing") or "disambiguation" in page.get("pageprops", {}):
        return None
    summary = short_summary(page.get("extract"))
    if not summary:
        return None
    url = page.get("fullurl") or "https://en.wikipedia.org/wiki/" + quote(page["title"].replace(" ", "_"))
    return {"title": page["title"], "summary": summary, "url": url}


def fetch_summary(search, get=requests.get):
    """Return {"title", "summary", "url"} for a search, or None if nothing fits.

    Tries the exact article title first, then a search by name, then the name
    plus its subject or interest (which settles words like "Interference").
    """
    if search.get("title"):
        found = _query({"titles": search["title"]}, get)
        if found:
            return found
    for phrase in (search["query"], f"{search['query']} {search['context']}"):
        found = _query({"generator": "search", "gsrsearch": phrase, "gsrlimit": "1"}, get)
        if found:
            return found
    return None


def _try_fetch(search, get):
    try:
        return True, fetch_summary(search, get=get)
    except InfoSourceError:
        return False, None


def lookup_many(db, searches, get=requests.get, now=time.time, live=MAX_LIVE_LOOKUPS):
    """Return {search key: info or None}, reading the cache first.

    Up to `live` uncached searches are fetched from Wikipedia in parallel. A
    search that fails (no network, rate limit) maps to None and is retried on
    the next visit; one that finds nothing is cached like a result.
    """
    results = {}
    missing = []
    for search in searches:
        key = search["key"]
        if key in results:
            continue
        row = db.execute(
            "SELECT fetched_at, payload FROM topic_info WHERE key = ?", (key,)
        ).fetchone()
        results[key] = None
        if row is not None and now() - row["fetched_at"] < CACHE_TTL_SECONDS:
            results[key] = json.loads(row["payload"])
        else:
            missing.append(search)

    to_fetch = missing[:live]
    if not to_fetch:
        return results

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(to_fetch))) as pool:
        fetched = list(pool.map(lambda search: _try_fetch(search, get), to_fetch))

    for search, (ok, info) in zip(to_fetch, fetched):
        if not ok:
            continue
        results[search["key"]] = info
        db.execute(
            "INSERT INTO topic_info (key, fetched_at, payload) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET fetched_at = excluded.fetched_at, "
            "payload = excluded.payload",
            (search["key"], int(now()), json.dumps(info)),
        )
    db.commit()
    return results
