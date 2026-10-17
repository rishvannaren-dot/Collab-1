import os

from flask import Flask, g, render_template

from . import db
from .routes import auth, main, onboarding, videos
from .services import preferences


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev"),
        DATABASE=os.path.join(app.instance_path, "focusfeed.db"),
        YOUTUBE_API_KEY=os.environ.get("YOUTUBE_API_KEY"),
    )
    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    with app.app_context():
        db.init_db()  # safe to repeat: tables are only created if missing

    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(onboarding.bp)
    app.register_blueprint(videos.bp)

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

    return app
