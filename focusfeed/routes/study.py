from flask import Blueprint, abort, flash, g, redirect, request, url_for

from ..db import get_db
from ..services import cards, plan, preferences
from . import helpers
from .auth import login_required

bp = Blueprint("study", __name__)


@bp.route("/study/<subject_key>/<slug>/start", methods=("POST",))
@login_required
def start(subject_key, slug):
    """Make this chapter the subject's chapter for this week, starting today."""
    db = get_db()
    prefs = preferences.get_preferences(db, g.user["id"])
    if prefs is None or subject_key not in cards.SUBJECTS_BY_GOAL.get(prefs["goal"], []):
        abort(404)
    chapters = cards.grade_chapters(cards.load_syllabus(), subject_key, prefs["grade"])
    index = next((i for i, c in enumerate(chapters) if cards.slugify(c["name"]) == slug), None)
    if index is None:
        abort(404)

    plan.start_chapter(db, g.user["id"], subject_key, index, helpers.today())
    flash(f"{chapters[index]['name']} is this week's chapter. Day 1 starts today.", "success")
    return redirect(helpers.safe_next(request.form.get("next"), url_for("main.index")))
