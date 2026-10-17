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

- **Today page** (`/`): study cards and "From your topics".
  - For JEE, NEET, or Board goals in grade 11 or 12, each subject follows a **week plan** through the grade's chapters in `focusfeed/data/syllabus.json`: day 1 is the chapter's first topic, one topic a day in textbook order with no repeats, then a review day, a practice day if there is room, and a rest day on day 7. The next chapter starts on day 8.
  - A plan starts at chapter 1 on the day the student finishes onboarding, and restarts if they change grade or goal. "Study this chapter this week" on any chapter page makes that chapter day 1 today.
  - Students who onboarded before plans existed follow a shared Monday-to-Sunday rotation until they pick a chapter or change grade or goal.
  - Each followed interest gets one thing to explore per day, from `focusfeed/data/interests.json`.
  - Every card shows a one- or two-line explanation from Wikipedia (see below).
- **Chapter pages** (`/study/<subject>/<chapter>`): every topic in a chapter with its explanation. Card titles and topic chips link here.
- **Study record**: every topic on Today and on chapter pages asks "How well do you know it?" (Got it / Shaky / Lost me). Chapter pages show "3 of 5 topics studied", and when every topic for today is marked, Today says so and suggests nothing more. Only dates are stored, never times.
- **Revise today**: topics the student marked come back on Today for a quick recall check (a prompt like "Write the formula for Gauss's law and the SI unit of each quantity", the saved summary behind "Show summary", then "I remembered" or "Not yet"). "Got it" topics return after 3 days, then 7, 14, 30 and every 60; "Not yet", "Shaky" and "Lost me" come back tomorrow. At most 5 a day, oldest first, never a backlog count (`services/revision.py`).
- **Progress** (`/progress`): per subject and chapter, how many topics are marked, with a "Needs work" list of Shaky and Lost-me topics. There are no streaks, points or badges, on purpose. If a topic is renamed in `syllabus.json`, its old marks no longer count; a test lists every topic key so renames are noticed.
- **Explore** (`/explore`): a searchable table of contents of the student's own choices: their grade and goal's chapters (with "x of N studied", a "This week" badge and "Study this week" buttons) and the 8 interests with Follow / Unfollow. Nothing on it is ranked or comes from outside `syllabus.json` and `interests.json`.
- **Topic pages** (`/topics/<interest>`): everything to explore for one interest, plus videos. The followed topics in the sidebar link here.
- **Explanations**: looked up on Wikipedia (Google's web search API is closed to new projects; most of Google's topic summaries come from Wikipedia anyway). No key is needed.
  - `focusfeed/data/wiki_titles.json` maps syllabus topics to the right article when the name alone would find the wrong one (for example "Transformers" to "Transformer"). Other topics are searched by name.
  - Results are cached for 7 days, so each topic is looked up at most once a week. If Wikipedia can't be reached, cards say "No summary yet" and it tries again next visit.
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

## Accounts

- Sign-up asks for a nickname (3-30 letters, numbers, `.`, `_` or `-`); "Alice" and "alice" are the same account.
- Straight after sign-up the student can make a **recovery key** (like `ABCD-EFGH-JKLM-NPQR`). With it, "Forgot password?" on the sign-in page sets a new password. There is no email, on purpose. Each key works once; only its hash is stored.
- The Account page (`/account`) has Change password, a new recovery key, and "Sign out of all other devices".
- It also has **Download my data** (a JSON file) and **Delete my account** (password plus typed username; deletes every row about the student at once). Sign-up stores when the student agreed to the privacy notes and which version (`PRIVACY_VERSION` in `services/account.py`).
- Any new table with a `user_id` column must be added to `USER_TABLES` in `services/account.py`, or a test fails. That keeps download and delete complete.

## For the team

Run these in the project folder with the virtual environment active:

```bash
flask --app run users set-password USERNAME   # a student lost their password and key
flask --app run users unlock USERNAME         # clear the 15-minute sign-in lock
flask --app run users export USERNAME -o x.json  # a guardian asks for the data
flask --app run users delete USERNAME         # a guardian asks for deletion (asks to confirm)
flask --app run backup                        # dated copy in instance/backups, keeps 7
```

### Changing the database

Never edit `focusfeed/schema.sql` (it is the starting point for every existing database). Add a numbered entry to `MIGRATIONS` in `focusfeed/migrations.py` instead; it runs once on every database the next time the app starts.

## Project structure

```
focus-feed/
  run.py                 entry point
  requirements.txt
  .env.example
  focusfeed/
    __init__.py          create_app(): config, database, blueprints
    db.py                SQLite connection
    schema.sql           users, preferences, video_cache, topic_info, login_failures
    routes/              auth, main (today + privacy), onboarding, topics, videos
    services/            logic with no Flask in it: preferences, cards, explore,
                         topic_info, videos, login_limits
    data/                syllabus.json, interests.json, wiki_titles.json,
                         channels.json, videos.json
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
