# Focus Feed

A Python web app that shows only the content you choose: study cards and curated videos based on your interests, grade, and goals, instead of an endless feed.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

Then open http://127.0.0.1:5000, register, and pick your interests, grade, and goal. The database is created automatically on first run.

Run the tests with `pytest`.

## Settings (`.env`, never commit it)

- `SECRET_KEY`: signs login sessions. Leave it empty while developing and the app saves a random key in `instance/secret_key`. On a real server, set it to a long random string (for example the output of `python -c "import secrets; print(secrets.token_hex(32))"`).
- `YOUTUBE_API_KEY`: turns on live video search. Get one from Google Cloud (enable "YouTube Data API v3"). Without it the app still works and shows hand-picked videos plus YouTube search links.

## How it works

- **Today page** (`/`): study cards. For JEE, NEET, or Board goals in grade 11 or 12, each subject gets one chapter per week and one topic per day, taken from `focusfeed/data/syllabus.json`.
- **Videos page** (`/videos`): one section per topic.
  - Syllabus topics keep only videos from channels in `focusfeed/data/channels.json`.
  - Other interests only get the length and view filters.
  - Filters: 4 minutes to 3 hours long, at least 1,000 views.
  - Live results are cached for 6 hours. Each search costs about 101 of the 10,000 daily quota units, and at most 6 topics are searched per page load.
  - If live search is off or fails, the page shows the hand-picked videos and a friendly note.
- **Preferences** (`/onboarding`): the same form is used for first-time setup and for editing later.

### Adding hand-picked videos

Add entries to `focusfeed/data/videos.json`. `tags` is the lower-case chapter name (for example `"electrostatics"`) or an interest key (for example `"sports"`):

```json
{
  "videos": [
    {
      "id": "YOUTUBE_VIDEO_ID",
      "title": "Gauss's law",
      "channel": "Khan Academy",
      "seconds": 750,
      "tags": ["electrostatics"]
    }
  ]
}
```

The list ships empty on purpose: add only videos someone on the team has watched.

## Project structure

```
focus-feed/
  run.py                 entry point
  requirements.txt
  .env.example
  focusfeed/
    __init__.py          create_app(): config, database, blueprints
    db.py                SQLite connection
    schema.sql           users, preferences, video_cache
    routes/              auth, main (today + privacy), onboarding, videos
    services/            logic with no Flask in it: preferences, cards, videos
    data/                syllabus.json, channels.json, videos.json
    templates/
    static/
  tests/                 pytest
```

Routes only handle requests and render pages. Anything that decides what to show goes in `services/` so it can be tested on its own.

## Collaborating

Work on a branch, push it, and open a pull request:

```bash
git checkout -b feature/my-change
git push -u origin feature/my-change
```
