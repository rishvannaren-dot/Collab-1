from datetime import date, datetime

from flask import Blueprint, g, redirect, render_template, url_for

from ..db import get_db
from ..services import cards as cards_service
from ..services import preferences
from .auth import login_required

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

    cards = cards_service.build_cards(prefs, cards_service.load_syllabus(), date.today())
    return render_template(
        "index.html",
        prefs=prefs,
        cards=cards,
        goal_label=preferences.GOALS.get(prefs["goal"], ""),
        greeting=greeting_for(datetime.now().hour),
        today=date.today(),
    )


@bp.route("/privacy")
def privacy():
    return render_template("privacy.html")
