import os
import secrets
from datetime import timedelta

from flask import Flask, flash, g, redirect, render_template, request, url_for
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from . import cli, db, security
from .routes import account, auth, browse, main, onboarding, study, topics, videos
from .routes.helpers import format_date, safe_next, short_date
from .services import cards, preferences

csrf = CSRFProtect()

# The placeholder in .env.example; treated as "not set".
PLACEHOLDER_SECRET = "change-me"


def load_secret_key(instance_path):
    """Return SECRET_KEY from the environment, or a random key saved in the instance folder.

    A fixed fallback like "dev" would let anyone forge a login cookie. The saved
    key keeps people signed in across restarts. Set SECRET_KEY on a real server.
    """
    key = os.environ.get("SECRET_KEY", "")
    if key and key != PLACEHOLDER_SECRET:
        return key
    path = os.path.join(instance_path, "secret_key")
    try:
        with open(path, encoding="utf-8") as f:
            key = f.read().strip()
    except FileNotFoundError:
        key = ""
    if not key:
        key = secrets.token_hex(32)
        # Readable only by the owner.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with open(fd, "w", encoding="utf-8") as f:
            f.write(key)
    return key


# Shown on error pages: (title, message).
ERRORS = {
    400: ("That request didn't look right", "Please go back and try again."),
    405: ("That didn't work", "That page can't be used like that. Please go back and try again."),
    413: ("That was too big to send", "Please go back and send something smaller."),
    500: ("Something went wrong", "It's not you, it's us. Please try again in a moment."),
}


def debug_enabled(environ=os.environ):
    """Werkzeug's debugger runs any code typed into it, so it is only on when asked for."""
    return environ.get("FLASK_DEBUG") == "1"


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=os.path.join(app.instance_path, "focusfeed.db"),
        YOUTUBE_API_KEY=os.environ.get("YOUTUBE_API_KEY"),
        TOPIC_INFO_LIVE=True,  # look up topic summaries on Wikipedia
        TOPIC_INFO_BUDGET_SECONDS=4,  # never keep a page waiting on Wikipedia longer
        APP_TIMEZONE="Asia/Kolkata",  # when "today" starts
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),  # "Keep me signed in"
        # Only over HTTPS: set FOCUSFEED_HTTPS=1 on a server with HTTPS, or login breaks.
        SESSION_COOKIE_SECURE=os.environ.get("FOCUSFEED_HTTPS") == "1",
        MAX_CONTENT_LENGTH=64 * 1024,  # forms are tiny; refuse anything bigger
        TRUST_PROXY=os.environ.get("TRUST_PROXY") == "1",  # behind nginx or similar
    )
    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = load_secret_key(app.instance_path)

    if app.config["TRUST_PROXY"]:
        # Use the client's address and https from the proxy's X-Forwarded-* headers.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    csrf.init_app(app)
    db.init_app(app)
    cli.init_app(app)
    security.init_app(app)
    with app.app_context():
        db.init_db()  # safe to repeat: tables are only created if missing

    app.register_blueprint(account.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(browse.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(onboarding.bp)
    app.register_blueprint(study.bp)
    app.register_blueprint(topics.bp)
    app.register_blueprint(videos.bp)
    app.add_template_filter(cards.slugify, "slug")
    app.add_template_filter(format_date, "date")
    app.add_template_filter(short_date, "short_date")

    @app.context_processor
    def inject_followed_topics():
        user = getattr(g, "user", None)
        if user is None:
            return {}
        prefs = preferences.get_preferences(db.get_db(), user["id"])
        keys = prefs["interests"] if prefs else []
        return {
            "followed": [
                {"key": key, "label": preferences.INTERESTS[key]}
                for key in keys
                if key in preferences.INTERESTS
            ]
        }

    @app.route("/favicon.ico")
    def favicon():
        # Browsers ask for this path even when the page names an SVG icon.
        return redirect(url_for("static", filename="favicon.svg"), code=301)

    @app.errorhandler(404)
    def not_found(error):
        return render_template("404.html"), 404

    def friendly_error(error):
        code = getattr(error, "code", 500) or 500
        title, message = ERRORS.get(code, ERRORS[500])
        return render_template("error.html", title=title, message=message), code

    for code in ERRORS:
        app.register_error_handler(code, friendly_error)

    @app.errorhandler(CSRFError)
    def csrf_failed(error):
        # Usually a form left open too long. Send them back to try again: to the
        # form itself if it has a page, else to where the form was shown.
        flash("That form expired. Please try again.", "error")
        rule = request.url_rule
        if rule is not None and "GET" in rule.methods:
            return redirect(request.path)
        return redirect(safe_next(request.form.get("next"), url_for("main.index")))

    return app
