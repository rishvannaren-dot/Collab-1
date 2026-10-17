from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ..db import get_db
from ..services import cards, plan, preferences, progress
from . import helpers
from .auth import login_required

bp = Blueprint("browse", __name__)


@bp.route("/explore")
@login_required
def index():
    """A table of contents of the student's own choices: their syllabus and the 8 interests."""
    db = get_db()
    prefs = preferences.get_preferences(db, g.user["id"])
    if prefs is None:
        return redirect(url_for("onboarding.onboarding"))
    syllabus = cards.load_syllabus()
    subjects = cards.syllabus_for(prefs, syllabus)
    this_week = {
        card["subject_key"]: card["slug"]
        for card in plan.todays_cards(db, g.user["id"], prefs, syllabus, helpers.today())
    }
    studied = progress.progress_for(db, g.user["id"])
    for subject in subjects:
        for chapter in subject["chapters"]:
            keys = [progress.topic_key(subject["key"], chapter["name"], t) for t in chapter["topics"]]
            chapter["done"] = sum(1 for key in keys if key in studied)
            chapter["this_week"] = this_week.get(subject["key"]) == chapter["slug"]

    followed = [k for k in prefs["interests"] if k in preferences.INTERESTS]
    others = [k for k in preferences.INTERESTS if k not in followed]
    return render_template(
        "explore.html",
        prefs=prefs,
        subjects=subjects,
        goal_label=preferences.GOALS.get(prefs["goal"], ""),
        interests=[(k, preferences.INTERESTS[k], True) for k in followed]
        + [(k, preferences.INTERESTS[k], False) for k in others],
    )


def change_follow(key, action):
    try:
        error = action(get_db(), g.user["id"], key)
    except KeyError:
        abort(404)
    return error


@bp.route("/topics/<key>/follow", methods=("POST",))
@login_required
def follow(key):
    error = change_follow(key, preferences.follow)
    if error:
        flash(error, "error")
    else:
        flash(f"Following {preferences.INTERESTS[key]}. It shows on Today from now on.", "success")
    return redirect(helpers.safe_next(request.form.get("next"), url_for("topics.interest", key=key)))


@bp.route("/topics/<key>/unfollow", methods=("POST",))
@login_required
def unfollow(key):
    error = change_follow(key, preferences.unfollow)
    if error:
        flash(error, "error")
    else:
        flash(f"Stopped following {preferences.INTERESTS[key]}.", "success")
    return redirect(helpers.safe_next(request.form.get("next"), url_for("topics.interest", key=key)))
