import os
import secrets

from flask import Flask, flash, g, redirect, render_template, request, url_for
from flask_wtf.csrf import CSRFError, CSRFProtect

from . import db
from .routes import auth, main, onboarding, topics, videos
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


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=os.path.join(app.instance_path, "focusfeed.db"),
        YOUTUBE_API_KEY=os.environ.get("YOUTUBE_API_KEY"),
        TOPIC_INFO_LIVE=True,  # look up topic summaries on Wikipedia
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = load_secret_key(app.instance_path)

    csrf.init_app(app)
    db.init_app(app)
    with app.app_context():
        db.init_db()  # safe to repeat: tables are only created if missing

    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(onboarding.bp)
    app.register_blueprint(topics.bp)
    app.register_blueprint(videos.bp)
    app.add_template_filter(cards.slugify, "slug")

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

    @app.errorhandler(404)
    def not_found(error):
        return render_template("404.html"), 404

    @app.errorhandler(CSRFError)
    def csrf_failed(error):
        # Usually a form left open too long. Send them back to the form to retry.
        flash("That form expired. Please try again.")
        if request.endpoint == "auth.logout":
            return redirect(url_for("main.index"))
        return redirect(request.path)

    return app
