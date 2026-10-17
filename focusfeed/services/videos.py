import json
import re
import time
from pathlib import Path
from urllib.parse import quote_plus

import requests

from . import source_health

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

MIN_SECONDS = 240  # drops Shorts and clips
MAX_SECONDS = 3 * 3600
MIN_VIEWS = 1000
SOURCE = "youtube"
CACHE_TTL_SECONDS = 6 * 3600
STALE_MAX_SECONDS = 7 * 24 * 3600  # older saved results still shown when YouTube fails
QUOTA_PAUSE_SECONDS = 3 * 3600  # after "daily quota used up", don't ask again for a while
MAX_LIVE_SEARCHES = 6  # each search costs ~101 of the 10,000 daily quota units
VIDEOS_PER_SECTION = 6

# Search phrases for interests that have no syllabus behind them.
INTEREST_QUERIES = {
    "science-tech": "science and technology explained for students",
    "education": "study skills and exam preparation tips",
    "sports": "sports analysis and training basics",
    "arts": "art and design tutorial for beginners",
    "music": "music theory and practice for beginners",
    "history": "history documentary explained",
    "business": "business and personal finance basics for students",
    "health": "fitness and healthy habits for students",
}


class VideoSourceError(Exception):
    """A problem talking to YouTube, worded so it can be shown to the user."""

    def __init__(self, message, retry_after=None, max_wait=source_health.MAX_BACKOFF_SECONDS):
        super().__init__(message)
        self.retry_after = retry_after
        self.max_wait = max_wait


class StaleVideos(VideoSourceError):
    """YouTube failed, but a saved result (up to STALE_MAX_SECONDS old) is available."""

    def __init__(self, error, videos):
        super().__init__(str(error), error.retry_after, error.max_wait)
        self.videos = videos


def load_json(name):
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def allowed_channels():
    return [c.lower() for c in load_json("channels.json")["channels"]]


def curated_videos():
    return load_json("videos.json")["videos"]


def search_link(query):
    return "https://www.youtube.com/results?search_query=" + quote_plus(query)


_DURATION = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


def parse_duration(iso):
    match = _DURATION.match(iso or "")
    if not match:
        return 0
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def format_duration(seconds):
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def filter_videos(videos, allow=None):
    """Keep videos of a sensible length with some views.

    If `allow` is given, also keep only videos from channels whose name contains
    one of the allowed names.
    """
    kept = []
    for video in videos:
        if not MIN_SECONDS <= video["seconds"] <= MAX_SECONDS:
            continue
        if video["views"] < MIN_VIEWS:
            continue
        if allow is not None:
            channel = video["channel"].lower()
            if not any(name in channel for name in allow):
                continue
        kept.append(video)
    return kept


def _error_for(response):
    """A VideoSourceError for a failed response (the page adds what it shows instead)."""
    try:
        reason = response.json()["error"]["errors"][0]["reason"]
    except (ValueError, KeyError, IndexError, TypeError):
        reason = ""
    retry_after = source_health.retry_after_seconds(response)
    if reason in ("quotaExceeded", "dailyLimitExceeded"):
        return VideoSourceError(
            "Today's YouTube search limit is used up.",
            retry_after=QUOTA_PAUSE_SECONDS,
            max_wait=QUOTA_PAUSE_SECONDS,
        )
    if reason == "rateLimitExceeded":
        return VideoSourceError("YouTube asked us to slow down.", retry_after=retry_after)
    if response.status_code in (400, 403):
        return VideoSourceError("YouTube rejected the API key. Check YOUTUBE_API_KEY.")
    return VideoSourceError("YouTube search failed.", retry_after=retry_after)


def search_youtube(api_key, query, get=requests.get, max_results=15):
    """Search YouTube and return videos with duration and view counts."""
    try:
        response = get(
            SEARCH_URL,
            params={
                "part": "snippet",
                "type": "video",
                "q": query,
                "maxResults": max_results,
                "safeSearch": "strict",
                "relevanceLanguage": "en",
                "key": api_key,
            },
            timeout=10,
        )
        if response.status_code != 200:
            raise _error_for(response)
        items = response.json().get("items", [])
        ids = [item["id"]["videoId"] for item in items if "videoId" in item.get("id", {})]
        if not ids:
            return []

        details_response = get(
            VIDEOS_URL,
            params={"part": "contentDetails,statistics", "id": ",".join(ids), "key": api_key},
            timeout=10,
        )
        if details_response.status_code != 200:
            raise _error_for(details_response)
        details = {d["id"]: d for d in details_response.json().get("items", [])}
    except requests.RequestException:
        raise VideoSourceError("Couldn't reach YouTube.")

    videos = []
    for item in items:
        video_id = item.get("id", {}).get("videoId")
        detail = details.get(video_id)
        if detail is None:
            continue
        videos.append(
            {
                "id": video_id,
                "title": item["snippet"]["title"],
                "channel": item["snippet"]["channelTitle"],
                "seconds": parse_duration(detail["contentDetails"].get("duration")),
                "views": int(detail.get("statistics", {}).get("viewCount", 0)),
            }
        )
    return videos


def read_cache(db, query, now, max_age):
    """Saved videos for `query` if they are younger than `max_age` seconds, else None."""
    row = db.execute(
        "SELECT fetched_at, payload FROM video_cache WHERE query = ?", (query,)
    ).fetchone()
    if row is None or now - row["fetched_at"] >= max_age:
        return None
    return json.loads(row["payload"])


def search_cached(db, api_key, query, get=requests.get, now=time.time):
    """Like search_youtube, but reuses a saved result for CACHE_TTL_SECONDS.

    If YouTube fails and an older saved result exists, raises StaleVideos
    carrying it, so the page can still show something.
    """
    current = now()
    fresh = read_cache(db, query, current, CACHE_TTL_SECONDS)
    if fresh is not None:
        return fresh
    try:
        videos = search_youtube(api_key, query, get=get)
    except VideoSourceError as error:
        saved = read_cache(db, query, current, STALE_MAX_SECONDS)
        if saved is not None:
            raise StaleVideos(error, saved) from error
        raise
    db.execute(
        "INSERT INTO video_cache (query, fetched_at, payload) VALUES (?, ?, ?) "
        "ON CONFLICT(query) DO UPDATE SET fetched_at = excluded.fetched_at, "
        "payload = excluded.payload",
        (query, int(current), json.dumps(videos)),
    )
    db.commit()
    # Only a real answer from YouTube ends a pause; a cache hit says nothing about it.
    source_health.record_success(db, SOURCE)
    return videos


def build_sections(prefs, cards):
    """Decide which topics the videos page should cover.

    Exam-syllabus topics (from the study cards) are strict: only allowlisted
    channels are kept. Other interests only get the length and view filters.
    """
    sections = []
    for card in cards:
        sections.append(
            {
                "title": f"{card['subject']}: {card['chapter']}",
                "query": card["query"],
                "strict": True,
                "tag": card["chapter"].lower(),
                # Physics and Chemistry both have "Thermodynamics", so anchors name the subject.
                "anchor": f"{card['subject_key']}-{card['slug']}",
            }
        )
    for key in prefs["interests"]:
        if key in ("science-tech", "education") and cards:
            continue  # already covered by the syllabus sections above
        query = INTEREST_QUERIES.get(key)
        if query:
            sections.append(
                {"title": key.replace("-", " ").title(), "query": query, "strict": False, "tag": key, "anchor": key}
            )
    return sections


def resolve_section(section, db, api_key, curated, allow, get=requests.get, live=True):
    """Return (videos, notice) for one section.

    With an API key and `live`, searches YouTube (through the cache). Without
    `live`, only saved results are used. Falls back to the hand-picked list.
    `notice` explains a live-search failure, else None. Failures pause YouTube
    for a while (services/source_health.py) and successes clear the pause.
    """
    allowlist = allow if section["strict"] else None
    videos = []
    notice = None

    if api_key and live:
        try:
            videos = filter_videos(search_cached(db, api_key, section["query"], get=get), allowlist)
        except StaleVideos as error:
            videos = filter_videos(error.videos, allowlist)
            notice = f"{error} Showing videos saved earlier."
            source_health.record_failure(db, SOURCE, time.time(), error.retry_after, error.max_wait)
        except VideoSourceError as error:
            notice = f"{error} Showing saved picks instead."
            source_health.record_failure(db, SOURCE, time.time(), error.retry_after, error.max_wait)
    elif api_key:
        saved = read_cache(db, section["query"], time.time(), STALE_MAX_SECONDS)
        if saved:
            videos = filter_videos(saved, allowlist)

    if not videos:
        # Hand-picked videos are trusted, so they skip the length/view/channel filters.
        videos = [v for v in curated if section["tag"] in [t.lower() for t in v.get("tags", [])]]

    return videos[:VIDEOS_PER_SECTION], notice
