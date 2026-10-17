from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from ..db import get_db
from ..services import preferences
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
            preferences.save_preferences(db, g.user["id"], cleaned)
            return redirect(url_for("main.index"))
        flash(error)
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
