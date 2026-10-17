import functools
import time

from flask import (
    Blueprint,
    flash,
    g,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import generate_password_hash

from ..db import get_db
from ..services import account, login_limits, recovery

bp = Blueprint("auth", __name__, url_prefix="/auth")

# Kept here too because older code imports it from this module.
MIN_PASSWORD_LENGTH = account.MIN_PASSWORD_LENGTH


def login_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("main.welcome"))
        return view(**kwargs)

    return wrapped


def sign_in(user_id, session_version, remember=False):
    session.clear()
    session.permanent = remember  # 30 days instead of until the browser closes
    session["user_id"] = user_id
    session["sv"] = session_version


def lock_minutes():
    return login_limits.WINDOW_SECONDS // 60


def render_new_key(key, intro, continue_url):
    """Show a recovery key once. It is never put in the session or a flash."""
    response = make_response(
        render_template("auth/new_key.html", key=key, intro=intro, continue_url=continue_url)
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = None
    if user_id is None:
        return
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    # A password change or "sign out everywhere" moves session_version on, which
    # ends every session made before it. Sessions from before this check have no
    # "sv", which counts as 0.
    if user is None or session.get("sv", 0) != user["session_version"]:
        session.clear()
        return
    g.user = user


@bp.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()

        error = account.username_error(username) or account.password_error(password)
        if error is None and not request.form.get("consent"):
            error = "Please confirm you are 18 or have a parent or guardian's permission."
        if error is None and account.username_taken(db, username):
            error = f"Username {username} is already taken."

        if error is None:
            now = int(time.time())
            cursor = db.execute(
                "INSERT INTO users (username, password_hash, created_at, consent_at, consent_version) "
                "VALUES (?, ?, ?, ?, ?)",
                (username, generate_password_hash(password), now, now, account.PRIVACY_VERSION),
            )
            db.commit()
            sign_in(cursor.lastrowid, 0)
            return redirect(url_for("account.recovery_key"))

        flash(error, "error")

    return render_template("auth/register.html")


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        now = int(time.time())
        lock = username.lower()  # "Alice" and "alice" share one counter

        if login_limits.is_locked(db, lock, now):
            flash(f"Too many failed sign-ins. Try again in {lock_minutes()} minutes.", "error")
            return render_template("auth/login.html")

        user = account.find_user(db, username)
        if not account.check_password(user, password):
            login_limits.record_failure(db, lock, now)
            flash("Incorrect username or password.", "error")
        else:
            login_limits.clear_failures(db, lock)
            sign_in(user["id"], user["session_version"], remember=bool(request.form.get("remember")))
            return redirect(url_for("main.index"))

    return render_template("auth/login.html")


@bp.route("/forgot", methods=("GET", "POST"))
def forgot():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        key = request.form.get("recovery_key", "")
        password = request.form.get("password", "")
        db = get_db()
        now = int(time.time())
        # Separate from the sign-in counter, so a locked-out student can still reset.
        lock = "reset:" + username.lower()

        error = account.password_error(password, request.form.get("confirm", ""))
        if error is None and login_limits.is_locked(db, lock, now):
            error = f"Too many tries. Try again in {lock_minutes()} minutes."
        if error is None:
            user = account.find_user(db, username)
            if not recovery.verify(db, user["id"] if user else None, key):
                login_limits.record_failure(db, lock, now)
                error = "That username and recovery key don't match."
            else:
                version = account.set_password(db, user["id"], password)
                new_key = recovery.set_key(db, user["id"], now)
                login_limits.clear_failures(db, lock)
                login_limits.clear_failures(db, username.lower())
                sign_in(user["id"], version)
                return render_new_key(
                    new_key,
                    "Your password is changed and your old key no longer works. "
                    "Here is your new recovery key.",
                    url_for("main.index"),
                )
        flash(error, "error")

    return render_template("auth/forgot.html")


@bp.route("/logout", methods=("POST",))
def logout():
    session.clear()
    return redirect(url_for("main.index"))
