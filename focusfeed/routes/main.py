from flask import Blueprint, g, redirect, render_template, url_for

from ..db import get_db
from ..services import cards as cards_service
from ..services import explore, preferences, recovery, topic_info
from . import helpers
from .auth import login_required
from .topics import attach_info

bp = Blueprint("main", __name__)


def greeting_for(hour):
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


@bp.route("/welcome")
def welcome():
    if g.user is not None:
        return redirect(url_for("main.index"))
    return render_template("welcome.html")


@bp.route("/")
@login_required
def index():
    prefs = preferences.get_preferences(get_db(), g.user["id"])
    if prefs is None:
        return redirect(url_for("onboarding.onboarding"))

    today = helpers.today()
    cards = cards_service.build_cards(prefs, cards_service.load_syllabus(), today)
    picks = explore.todays_picks(prefs["interests"], explore.load_interest_topics(), today)

    titles = topic_info.load_wiki_titles()
    for card in cards:
        card["search"] = topic_info.syllabus_search(card["topic"], card["subject"], titles)
    for pick in picks:
        pick["search"] = topic_info.interest_search(pick["article"], pick["label"])
    attach_info(cards + picks)

    return render_template(
        "index.html",
        prefs=prefs,
        cards=cards,
        picks=picks,
        goal_label=preferences.GOALS.get(prefs["goal"], ""),
        greeting=greeting_for(helpers.now().hour),
        today=today,
        has_recovery_key=recovery.key_created_at(get_db(), g.user["id"]) is not None,
    )


@bp.route("/privacy")
def privacy():
    return render_template("privacy.html")
