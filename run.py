from dotenv import load_dotenv

load_dotenv()  # reads SECRET_KEY / YOUTUBE_API_KEY from a local .env if present

from focusfeed import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
