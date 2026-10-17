import time

from flask import Blueprint, abort, current_app, g, redirect, render_template, url_for

from ..db import get_db
from ..services import cards as cards_service
from ..services import explore, plan, preferences, progress, source_health, topic_info
from ..services import videos as videos_service
from . import helpers
from .auth import login_required

bp = Blueprint("topics", __name__)


def live_lookups():
    """How many uncached Wikipedia lookups this page may make (0 turns them off)."""
    return topic_info.MAX_LIVE_LOOKUPS if current_app.config["TOPIC_INFO_LIVE"] else 0


WIKI_BUSY = "Wikipedia is busy right now, so some explanations are missing. Saved ones are shown."


def attach_info(items):
    """Look up every item's "search" and store the result in item["info"].

    Returns a notice to show when Wikipedia is paused and something is missing.
    """
    db = get_db()
    info = topic_info.lookup_many(
        db,
        [i["search"] for i in items],
        live=live_lookups(),
        budget=current_app.config["TOPIC_INFO_BUDGET_SECONDS"],
    )
    for item in items:
        item["info"] = info.get(item["search"]["key"])
    if any(item["info"] is None for item in items) and topic_info.source_busy(db):
        return WIKI_BUSY
    return None


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
    wiki_notice = attach_info(items)

    section = {
        "title": label,
        "query": videos_service.INTEREST_QUERIES[key],
        "strict": False,
        "tag": key,
    }
    api_key = current_app.config.get("YOUTUBE_API_KEY")
    found, _ = videos_service.resolve_section(
        section,
        db,
        api_key,
        videos_service.curated_videos(),
        videos_service.allowed_channels(),
        live=bool(api_key) and source_health.is_available(db, videos_service.SOURCE, time.time()),
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
        wiki_notice=wiki_notice,
    )


@bp.route("/study/<subject_key>/<slug>")
@login_required
def chapter(subject_key, slug):
    syllabus = cards_service.load_syllabus()
    found = cards_service.find_chapter(syllabus, subject_key, slug)
    if found is None:
        abort(404)
    subject, chapter = found

    db = get_db()
    prefs = preferences.get_preferences(db, g.user["id"])
    this_week = None  # today's card, if this is the subject's chapter this week
    can_start = False  # whether "Study this chapter this week" applies
    if prefs is not None:
        for card in plan.todays_cards(db, g.user["id"], prefs, syllabus, helpers.today()):
            if card["subject_key"] == subject_key and card["slug"] == slug:
                this_week = card
        can_start = (
            this_week is None
            and subject_key in cards_service.SUBJECTS_BY_GOAL.get(prefs["goal"], [])
            and chapter["grade"] == prefs["grade"]
        )
    today_topic = this_week["topic"] if this_week else None

    titles = topic_info.load_wiki_titles()
    studied = progress.progress_for(db, g.user["id"])
    items = [
        {
            "name": topic,
            "anchor": cards_service.slugify(topic),
            "key": progress.topic_key(subject_key, chapter["name"], topic),
            "studied": studied.get(progress.topic_key(subject_key, chapter["name"], topic)),
            "today": topic == today_topic,
            "search": topic_info.syllabus_search(topic, subject["label"], titles),
            "video_link": videos_service.search_link(
                f"{topic} {chapter['name']} Class {chapter['grade']}"
            ),
        }
        for topic in chapter["topics"]
    ]
    wiki_notice = attach_info(items)

    return render_template(
        "chapter.html",
        subject=subject,
        subject_key=subject_key,
        slug=slug,
        chapter=chapter,
        items=items,
        this_week=this_week,
        can_start=can_start,
        done=sum(1 for item in items if item["studied"]),
        neighbours=cards_service.neighbours(syllabus, subject_key, slug, chapter["grade"]),
        wiki_notice=wiki_notice,
        today=helpers.today(),
    )
