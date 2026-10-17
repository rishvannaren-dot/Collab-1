from datetime import date

from flask import Blueprint, current_app, g, redirect, render_template, url_for

from ..db import get_db
from ..services import cards as cards_service
from ..services import preferences
from ..services import videos as videos_service
from .auth import login_required

bp = Blueprint("videos", __name__)


@bp.route("/videos")
@login_required
def index():
    db = get_db()
    prefs = preferences.get_preferences(db, g.user["id"])
    if prefs is None:
        return redirect(url_for("onboarding.onboarding"))

    cards = cards_service.build_cards(prefs, cards_service.load_syllabus(), date.today())
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

    resolved = []
    for number, section in enumerate(sections):
        videos, notice = videos_service.resolve_section(
            section,
            db,
            api_key,
            curated,
            allow,
            live=number < videos_service.MAX_LIVE_SEARCHES,
        )
        if notice and notice not in notices:
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
