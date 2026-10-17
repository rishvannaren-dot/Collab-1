from dotenv import load_dotenv

load_dotenv()  # reads SECRET_KEY / YOUTUBE_API_KEY from a local .env if present

from focusfeed import create_app, debug_enabled  # noqa: E402

app = create_app()

if __name__ == "__main__":
    # Auto-reload and the debugger only with FLASK_DEBUG=1 (in .env while developing).
    app.run(debug=debug_enabled())
