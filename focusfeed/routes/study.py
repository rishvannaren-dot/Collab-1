from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ..db import get_db
from ..services import cards, plan, preferences, progress
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


@bp.route("/study/mark", methods=("POST",))
@login_required
def mark():
    """Mark a topic as studied today, with how sure the student feels (1-3)."""
    key = request.form.get("topic_key", "")
    confidence = request.form.get("confidence", "")
    if confidence not in ("1", "2", "3") or not progress.valid_key(cards.load_syllabus(), key):
        abort(400)
    progress.mark(get_db(), g.user["id"], key, int(confidence), helpers.today())
    return redirect(helpers.safe_next(request.form.get("next"), url_for("main.index")))


@bp.route("/study/unmark", methods=("POST",))
@login_required
def unmark():
    key = request.form.get("topic_key", "")
    if not progress.valid_key(cards.load_syllabus(), key):
        abort(400)
    progress.unmark(get_db(), g.user["id"], key)
    return redirect(helpers.safe_next(request.form.get("next"), url_for("main.index")))


@bp.route("/progress", endpoint="progress")
@login_required
def progress_page():
    db = get_db()
    prefs = preferences.get_preferences(db, g.user["id"])
    if prefs is None:
        return redirect(url_for("onboarding.onboarding"))
    syllabus = cards.load_syllabus()
    subject_keys = cards.SUBJECTS_BY_GOAL.get(prefs["goal"], [])
    studied = progress.progress_for(db, g.user["id"])
    return render_template(
        "progress.html",
        prefs=prefs,
        goal_label=preferences.GOALS.get(prefs["goal"], ""),
        subjects=progress.coverage(syllabus, subject_keys, prefs["grade"], studied),
        needs_work=progress.needs_work(syllabus, studied, subject_keys, prefs["grade"]),
        any_studied=bool(studied),
        labels=progress.CONFIDENCE,
    )
