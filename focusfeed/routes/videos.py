import time

from flask import Blueprint, current_app, g, redirect, render_template, url_for

from ..db import get_db
from ..services import cards as cards_service
from ..services import plan, preferences, source_health
from ..services import videos as videos_service
from . import helpers
from .auth import login_required

bp = Blueprint("videos", __name__)


@bp.route("/videos")
@login_required
def index():
    db = get_db()
    prefs = preferences.get_preferences(db, g.user["id"])
    if prefs is None:
        return redirect(url_for("onboarding.onboarding"))

    cards = plan.todays_cards(db, g.user["id"], prefs, cards_service.load_syllabus(), helpers.today())
    sections = videos_service.build_sections(prefs, cards)

    api_key = current_app.config.get("YOUTUBE_API_KEY")
    curated = videos_service.curated_videos()
    allow = videos_service.allowed_channels()

    notices = []
    if not api_key:
        notices.append(
            "Live YouTube search is off (no YOUTUBE_API_KEY set). "
            "Showing hand-picked videos and search links."
        )

    # Live search only while YouTube isn't paused after an error, and never again
    # on this page after the first failure (saved results are still shown).
    live = bool(api_key) and source_health.is_available(db, videos_service.SOURCE, time.time())
    if api_key and not live:
        notices.append("YouTube search is paused for a while after an error. Showing saved videos.")

    resolved = []
    for number, section in enumerate(sections):
        videos, notice = videos_service.resolve_section(
            section,
            db,
            api_key,
            curated,
            allow,
            live=live and number < videos_service.MAX_LIVE_SEARCHES,
        )
        if notice:
            live = False
            if notice not in notices:
                notices.append(notice)
        resolved.append(
            {
                **section,
                "videos": videos,
                "link": videos_service.search_link(section["query"]),
            }
        )

    return render_template(
        "videos.html",
        sections=resolved,
        notices=notices,
        format_duration=videos_service.format_duration,
    )
