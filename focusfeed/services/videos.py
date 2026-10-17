import json
import re
import time
from pathlib import Path
from urllib.parse import quote_plus

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

MIN_SECONDS = 240  # drops Shorts and clips
MAX_SECONDS = 3 * 3600
MIN_VIEWS = 1000
CACHE_TTL_SECONDS = 6 * 3600
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
    try:
        reason = response.json()["error"]["errors"][0]["reason"]
    except (ValueError, KeyError, IndexError, TypeError):
        reason = ""
    if reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"):
        return "Today's YouTube search limit is used up. Showing saved picks instead."
    if response.status_code in (400, 403):
        return "YouTube rejected the API key. Check YOUTUBE_API_KEY. Showing saved picks instead."
    return "YouTube search failed. Showing saved picks instead."


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
            raise VideoSourceError(_error_for(response))
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
            raise VideoSourceError(_error_for(details_response))
        details = {d["id"]: d for d in details_response.json().get("items", [])}
    except requests.RequestException:
        raise VideoSourceError("Couldn't reach YouTube. Showing saved picks instead.")

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


def search_cached(db, api_key, query, get=requests.get, now=time.time):
    """Like search_youtube, but reuses a saved result for CACHE_TTL_SECONDS."""
    row = db.execute(
        "SELECT fetched_at, payload FROM video_cache WHERE query = ?", (query,)
    ).fetchone()
    if row is not None and now() - row["fetched_at"] < CACHE_TTL_SECONDS:
        return json.loads(row["payload"])

    videos = search_youtube(api_key, query, get=get)
    db.execute(
        "INSERT INTO video_cache (query, fetched_at, payload) VALUES (?, ?, ?) "
        "ON CONFLICT(query) DO UPDATE SET fetched_at = excluded.fetched_at, "
        "payload = excluded.payload",
        (query, int(now()), json.dumps(videos)),
    )
    db.commit()
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
            }
        )
    for key in prefs["interests"]:
        if key in ("science-tech", "education") and cards:
            continue  # already covered by the syllabus sections above
        query = INTEREST_QUERIES.get(key)
        if query:
            sections.append(
                {"title": key.replace("-", " ").title(), "query": query, "strict": False, "tag": key}
            )
    return sections


def resolve_section(section, db, api_key, curated, allow, get=requests.get, live=True):
    """Return (videos, notice) for one section.

    Tries live search first when an API key is set and `live` is true; falls back
    to the hand-picked list. `notice` explains a live-search failure, else None.
    """
    allowlist = allow if section["strict"] else None
    videos = []
    notice = None

    if api_key and live:
        try:
            videos = filter_videos(search_cached(db, api_key, section["query"], get=get), allowlist)
        except VideoSourceError as error:
            notice = str(error)

    if not videos:
        # Hand-picked videos are trusted, so they skip the length/view/channel filters.
        videos = [v for v in curated if section["tag"] in [t.lower() for t in v.get("tags", [])]]

    return videos[:VIDEOS_PER_SECTION], notice
