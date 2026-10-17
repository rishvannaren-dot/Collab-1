from flask import Blueprint, abort, current_app, g, redirect, render_template, url_for

from ..db import get_db
from ..services import cards as cards_service
from ..services import explore, preferences, topic_info
from ..services import videos as videos_service
from . import helpers
from .auth import login_required

bp = Blueprint("topics", __name__)


def live_lookups():
    """How many uncached Wikipedia lookups this page may make (0 turns them off)."""
    return topic_info.MAX_LIVE_LOOKUPS if current_app.config["TOPIC_INFO_LIVE"] else 0


def attach_info(items):
    """Look up every item's "search" and store the result in item["info"]."""
    info = topic_info.lookup_many(get_db(), [i["search"] for i in items], live=live_lookups())
    for item in items:
        item["info"] = info.get(item["search"]["key"])


@bp.route("/topics/<key>")
@login_required
def interest(key):
    if key not in preferences.INTERESTS:
        abort(404)
    db = get_db()
    prefs = preferences.get_preferences(db, g.user["id"])
    if prefs is None:
        return redirect(url_for("onboarding.onboarding"))

    label = preferences.INTERESTS[key]
    topics = explore.load_interest_topics()
    picks = explore.todays_picks(prefs["interests"], topics, helpers.today())
    today_article = next((p["article"] for p in picks if p["key"] == key), None)

    items = [
        {
            "name": explore.display_name(article),
            "today": article == today_article,
            "search": topic_info.interest_search(article, label),
        }
        for article in topics.get(key, [])
    ]
    items.sort(key=lambda item: not item["today"])  # today's pick first
    attach_info(items)

    section = {
        "title": label,
        "query": videos_service.INTEREST_QUERIES[key],
        "strict": False,
        "tag": key,
    }
    found, _ = videos_service.resolve_section(
        section,
        db,
        current_app.config.get("YOUTUBE_API_KEY"),
        videos_service.curated_videos(),
        videos_service.allowed_channels(),
    )

    return render_template(
        "topic.html",
        key=key,
        label=label,
        following=key in prefs["interests"],
        items=items,
        videos=found,
        search_link=videos_service.search_link(section["query"]),
        format_duration=videos_service.format_duration,
    )


@bp.route("/study/<subject_key>/<slug>")
@login_required
def chapter(subject_key, slug):
    syllabus = cards_service.load_syllabus()
    found = cards_service.find_chapter(syllabus, subject_key, slug)
    if found is None:
        abort(404)
    subject, chapter = found

    prefs = preferences.get_preferences(get_db(), g.user["id"])
    today_topic = None
    if prefs is not None:
        for card in cards_service.build_cards(prefs, syllabus, helpers.today()):
            if card["subject_key"] == subject_key and card["slug"] == slug:
                today_topic = card["topic"]

    titles = topic_info.load_wiki_titles()
    items = [
        {
            "name": topic,
            "anchor": cards_service.slugify(topic),
            "today": topic == today_topic,
            "search": topic_info.syllabus_search(topic, subject["label"], titles),
            "video_link": videos_service.search_link(
                f"{topic} {chapter['name']} Class {chapter['grade']}"
            ),
        }
        for topic in chapter["topics"]
    ]
    attach_info(items)

    return render_template("chapter.html", subject=subject, chapter=chapter, items=items)
