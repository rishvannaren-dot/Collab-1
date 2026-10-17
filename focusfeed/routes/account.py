import json
import time

from flask import (
    Blueprint,
    Response,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..db import get_db
from ..services import account, login_limits, preferences, recovery
from .auth import login_required, lock_minutes, render_new_key

bp = Blueprint("account", __name__, url_prefix="/account")


def password_ok(db, password):
    """Check the signed-in user's password. Wrong guesses count as failed sign-ins,
    so someone who finds an unlocked device can't keep guessing here either."""
    lock = g.user["username"].lower()
    now = int(time.time())
    if login_limits.is_locked(db, lock, now):
        flash(f"Too many wrong passwords. Try again in {lock_minutes()} minutes.", "error")
        return False
    if not account.check_password(g.user, password):
        login_limits.record_failure(db, lock, now)
        flash("That isn't your current password.", "error")
        return False
    login_limits.clear_failures(db, lock)
    return True


@bp.route("")
@login_required
def index():
    db = get_db()
    prefs = preferences.get_preferences(db, g.user["id"])
    return render_template(
        "account/index.html",
        prefs=prefs,
        goal_label=preferences.GOALS.get(prefs["goal"], "") if prefs else "",
        interests=preferences.INTERESTS,
        key_created_at=recovery.key_created_at(db, g.user["id"]),
        privacy_version=account.PRIVACY_VERSION,
    )


@bp.route("/password", methods=("GET", "POST"))
@login_required
def password():
    if request.method == "POST":
        db = get_db()
        new = request.form.get("password", "")
        error = account.password_error(new, request.form.get("confirm", ""))
        if error is not None:
            flash(error, "error")
        elif password_ok(db, request.form.get("current", "")):
            # This device stays signed in; every other one is signed out.
            session["sv"] = account.set_password(db, g.user["id"], new)
            flash("Password changed. Your other devices are signed out.", "success")
            return redirect(url_for("account.index"))
    return render_template("account/password.html")


@bp.route("/recovery-key", methods=("GET", "POST"))
@login_required
def recovery_key():
    db = get_db()
    has_prefs = preferences.get_preferences(db, g.user["id"]) is not None
    continue_url = url_for("account.index") if has_prefs else url_for("onboarding.onboarding")

    # Asking for the password stops someone with a borrowed, signed-in device
    # from making a key and using it to take over the account later.
    if request.method == "POST" and password_ok(db, request.form.get("current", "")):
        key = recovery.set_key(db, g.user["id"], time.time())
        return render_new_key(
            key,
            "If you forget your password, this key lets you set a new one.",
            continue_url,
        )
    return render_template(
        "account/recovery_key.html",
        key_created_at=recovery.key_created_at(db, g.user["id"]),
        continue_url=continue_url,
    )


@bp.route("/sign-out-everywhere", methods=("POST",))
@login_required
def sign_out_everywhere():
    session["sv"] = account.bump_session(get_db(), g.user["id"])
    flash("Signed out of every other device.", "success")
    return redirect(url_for("account.index"))


@bp.route("/export")
@login_required
def export():
    data = account.export_user(get_db(), g.user["id"], time.time())
    return Response(
        json.dumps(data, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={
            "Content-Disposition": "attachment; filename=focusfeed-my-data.json",
            "Cache-Control": "no-store",
        },
    )


@bp.route("/delete", methods=("GET", "POST"))
@login_required
def delete():
    if request.method == "POST":
        db = get_db()
        typed = request.form.get("confirm_username", "").strip()
        if typed.lower() != g.user["username"].lower():
            flash("Type your username exactly to confirm.", "error")
        elif password_ok(db, request.form.get("current", "")):
            account.delete_user(db, g.user["id"])
            session.clear()
            flash("Your account and everything stored about it were deleted.", "success")
            return redirect(url_for("main.welcome"))
    return render_template("account/delete.html")
