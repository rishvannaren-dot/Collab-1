"""One- or two-line explanations of topics, looked up on Wikipedia and cached.

Google's web search API is closed to new projects, so this uses Wikipedia, which
is where most of Google's own topic summaries come from. No API key is needed.
"""

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests

from . import source_health
from .clock import IST

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

API_URL = "https://en.wikipedia.org/w/api.php"
# Wikimedia asks every client to say who it is.
USER_AGENT = "FocusFeed/0.1 (student project; https://github.com/rishvannaren-dot/Collab-1)"

SOURCE = "wikipedia"
CACHE_TTL_SECONDS = 7 * 24 * 3600
# Older copies are still shown when Wikipedia can't be reached, up to this age.
STALE_MAX_SECONDS = 90 * 24 * 3600
TIMEOUT = (3, 5)  # seconds to connect, seconds to read
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

    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


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
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        raise InfoSourceError("Couldn't reach Wikipedia.")
    if response.status_code != 200:
        raise InfoSourceError(
            f"Wikipedia answered with status {response.status_code}.",
            retry_after=source_health.retry_after_seconds(response),
        )
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


def with_checked(info, fetched_at):
    """A copy of `info` saying when it was fetched, as an ISO date in India."""
    if info is None:
        return None
    return {**info, "checked_on": datetime.fromtimestamp(fetched_at, IST).date().isoformat()}


def source_busy(db, now=None):
    """True while Wikipedia is paused after a failure."""
    return not source_health.is_available(db, SOURCE, time.time() if now is None else now)


def lookup_many(db, searches, get=requests.get, now=time.time, live=MAX_LIVE_LOOKUPS, budget=None):
    """Return {search key: info or None}, reading the cache first.

    Up to `live` uncached searches are fetched from Wikipedia in parallel,
    unless Wikipedia is paused after an earlier failure. The first failure
    stops the rest of the batch, and nothing waits longer than `budget`
    seconds. A search that fails maps to its last saved copy (up to 90 days
    old) or None, and is retried later; one that finds nothing is cached like
    a result. Every result carries "checked_on", the date it was fetched.
    """
    current = now()
    keys = list(dict.fromkeys(search["key"] for search in searches))
    rows = {}
    if keys:
        marks = ",".join("?" * len(keys))
        query = f"SELECT key, fetched_at, payload FROM topic_info WHERE key IN ({marks})"
        rows = {row["key"]: row for row in db.execute(query, keys)}

    results, stale, missing, seen = {}, {}, [], set()
    for search in searches:
        key = search["key"]
        if key in seen:
            continue
        seen.add(key)
        results[key] = None
        row = rows.get(key)
        if row is not None:
            info = json.loads(row["payload"])
            age = current - row["fetched_at"]
            if age < CACHE_TTL_SECONDS:
                results[key] = with_checked(info, row["fetched_at"])
                continue
            if age < STALE_MAX_SECONDS and info is not None:
                stale[key] = with_checked(info, row["fetched_at"])
        missing.append(search)

    to_fetch = missing[:live]
    if to_fetch and source_health.is_available(db, SOURCE, current):
        fetched, failure = _fetch_all(to_fetch, get, budget)
        for key, info in fetched.items():
            results[key] = with_checked(info, current)
            db.execute(
                "INSERT INTO topic_info (key, fetched_at, payload) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET fetched_at = excluded.fetched_at, "
                "payload = excluded.payload",
                (key, int(current), json.dumps(info)),
            )
        db.commit()
        if failure is not None:
            source_health.record_failure(db, SOURCE, current, failure.retry_after)
        elif fetched:
            source_health.record_success(db, SOURCE)

    for key, info in stale.items():
        if results[key] is None:
            results[key] = info
    return results


def _fetch_all(searches, get, budget):
    """Fetch in parallel. Returns ({key: info}, first InfoSourceError or None).

    Threads still running at the deadline are abandoned and finish on their
    own. That is only safe because they never touch SQLite: all database
    writes happen on the request's thread, in lookup_many.
    """
    stop = threading.Event()  # set by the first failure, so the rest don't start

    def work(search):
        if stop.is_set():
            return search["key"], False, None, None
        try:
            return search["key"], True, fetch_summary(search, get=get), None
        except InfoSourceError as error:
            stop.set()
            return search["key"], False, None, error

    pool = ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(searches)))
    futures = [pool.submit(work, search) for search in searches]
    done, _ = wait(futures, timeout=budget)
    pool.shutdown(wait=False, cancel_futures=True)

    fetched, failure = {}, None
    for future in done:
        key, ok, info, error = future.result()
        if ok:
            fetched[key] = info
        elif error is not None and failure is None:
            failure = error
    if len(done) < len(futures) and failure is None and not fetched:
        failure = InfoSourceError("Wikipedia took too long to answer.")
    return fetched, failure
