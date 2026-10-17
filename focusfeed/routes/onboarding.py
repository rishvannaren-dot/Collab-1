from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from ..db import get_db
from ..services import cards, plan, preferences
from . import helpers
from .auth import login_required

bp = Blueprint("onboarding", __name__)


@bp.route("/onboarding", methods=("GET", "POST"))
@login_required
def onboarding():
    db = get_db()

    if request.method == "POST":
        selected = request.form.getlist("interests")
        cleaned, error = preferences.validate_preferences(
            selected, request.form.get("grade"), request.form.get("goal")
        )
        if error is None:
            before = preferences.get_preferences(db, g.user["id"])
            preferences.save_preferences(db, g.user["id"], cleaned)
            # A new grade or goal means different chapters: start again from
            # chapter 1 today. Changing only interests leaves the plan alone.
            if before is None or (before["grade"], before["goal"]) != (cleaned["grade"], cleaned["goal"]):
                plan.reset_plans(
                    db,
                    g.user["id"],
                    cards.SUBJECTS_BY_GOAL.get(cleaned["goal"], []),
                    helpers.today(),
                )
            return redirect(url_for("main.index"))
        flash(error, "error")
        current = {
            "interests": selected,
            "grade": request.form.get("grade"),
            "goal": request.form.get("goal"),
        }
    else:
        current = preferences.get_preferences(db, g.user["id"]) or {
            "interests": [],
            "grade": None,
            "goal": None,
        }

    return render_template(
        "onboarding.html",
        current=current,
        interests=preferences.INTERESTS,
        grades=preferences.GRADES,
        goals=preferences.GOALS,
    )
