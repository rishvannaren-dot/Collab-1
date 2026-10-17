import json
import re
from pathlib import Path

from .preferences import GOALS

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SUBJECTS_BY_GOAL = {
    "jee": ["physics", "chemistry", "maths"],
    "neet": ["physics", "chemistry", "biology"],
    "boards": ["physics", "chemistry", "maths", "biology"],
}


def load_syllabus():
    with open(DATA_DIR / "syllabus.json", encoding="utf-8") as f:
        return json.load(f)


def slugify(text):
    """"Work, Energy and Power" -> "work-energy-and-power", for URLs and page anchors."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def find_chapter(syllabus, subject_key, slug):
    """Return (subject, chapter) for a chapter's URL slug, or None."""
    subject = syllabus["subjects"].get(subject_key)
    if subject is None:
        return None
    for chapter in subject["chapters"]:
        if slugify(chapter["name"]) == slug:
            return subject, chapter
    return None


def build_cards(prefs, syllabus, today):
    """Build today's study cards.

    Each subject gets one chapter per week (rotating through the chapters for the
    user's grade) and one topic per day within that chapter. The result depends
    only on the profile and the date, so it is stable across page loads.
    """
    subject_keys = SUBJECTS_BY_GOAL.get(prefs["goal"], [])
    day = today.toordinal()
    goal_label = GOALS.get(prefs["goal"], "")
    cards = []

    for key in subject_keys:
        subject = syllabus["subjects"].get(key)
        if subject is None:
            continue
        chapters = [c for c in subject["chapters"] if c["grade"] == prefs["grade"]]
        if not chapters:
            continue

        index = (day // 7) % len(chapters)
        chapter = chapters[index]
        topic = chapter["topics"][day % len(chapter["topics"])]
        revise = chapters[index - 1]["name"] if len(chapters) > 1 else None

        cards.append(
            {
                "subject": subject["label"],
                "subject_key": key,
                "chapter": chapter["name"],
                "slug": slugify(chapter["name"]),
                "topic": topic,
                "topics": chapter["topics"],
                "revise": revise,
                "query": f"{chapter['name']} {topic} Class {prefs['grade']} {goal_label}",
            }
        )

    return cards
