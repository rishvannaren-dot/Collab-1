import json
import re
from datetime import date
from pathlib import Path

from .preferences import GOALS

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Students who onboarded before week plans existed follow this shared
# rotation: a Monday, so each chapter runs Monday to Sunday.
DEFAULT_START = date(2026, 1, 5)

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


def grade_chapters(syllabus, subject_key, grade):
    """The subject's chapters for one grade, in syllabus (textbook) order."""
    subject = syllabus["subjects"].get(subject_key)
    if subject is None:
        return []
    return [c for c in subject["chapters"] if c["grade"] == grade]


def syllabus_for(prefs, syllabus):
    """The student's syllabus: each subject of their goal with its chapters for their grade."""
    subjects = []
    for key in SUBJECTS_BY_GOAL.get(prefs["goal"], []):
        chapters = grade_chapters(syllabus, key, prefs["grade"])
        if not chapters:
            continue
        subjects.append(
            {
                "key": key,
                "label": syllabus["subjects"][key]["label"],
                "chapters": [
                    {
                        "name": c["name"],
                        "slug": slugify(c["name"]),
                        "grade": c["grade"],
                        "topics": c["topics"],
                        "index": i,
                    }
                    for i, c in enumerate(chapters)
                ],
            }
        )
    return subjects


def plan_position(chapter_index, start_on, today, n_chapters):
    """Where a plan is today: (chapter index, day 0-6 of the week, weeks since the start).

    A plan starts a chapter on `start_on` and moves to the next chapter every
    7 days, wrapping round after the last one.
    """
    days = max(0, (today - start_on).days)
    weeks = days // 7
    return (chapter_index + weeks) % n_chapters, days % 7, weeks


def week_slots(topics):
    """The 7 days of a chapter's week, in order.

    One "learn" day per topic in textbook order, then a "review" day, then
    "practice" days if there is room, and day 7 is always "rest". So 4 topics
    give learn x4, review, practice, rest; 5 topics give learn x5, review, rest.
    """
    kinds = [("learn", topic) for topic in topics[:6]]
    if len(kinds) < 6:
        kinds.append(("review", None))
    while len(kinds) < 6:
        kinds.append(("practice", None))
    kinds.append(("rest", None))
    return [{"day": n, "kind": kind, "topic": topic} for n, (kind, topic) in enumerate(kinds, 1)]


def build_cards(prefs, syllabus, today, plans=None):
    """Build today's study cards, one per subject of the student's goal.

    `plans` maps subject keys to {"chapter_index", "start_on"}: the chapter the
    student started and the day they started it. A subject without a plan
    follows a shared Monday-to-Sunday rotation from the grade's first chapter.
    """
    subject_keys = SUBJECTS_BY_GOAL.get(prefs["goal"], [])
    goal_label = GOALS.get(prefs["goal"], "")
    plans = plans or {}
    cards = []

    for key in subject_keys:
        chapters = grade_chapters(syllabus, key, prefs["grade"])
        if not chapters:
            continue
        plan = plans.get(key) or {"chapter_index": 0, "start_on": DEFAULT_START}
        index, day, weeks = plan_position(
            plan["chapter_index"], plan["start_on"], today, len(chapters)
        )
        chapter = chapters[index]
        slots = week_slots(chapter["topics"])
        slot = slots[day]
        topic = slot["topic"]
        # Only revise a chapter the plan has actually been through.
        revise = chapters[(index - 1) % len(chapters)]["name"] if weeks >= 1 and len(chapters) > 1 else None
        query_topic = f" {topic}" if topic else ""

        cards.append(
            {
                "subject": syllabus["subjects"][key]["label"],
                "subject_key": key,
                "chapter": chapter["name"],
                "slug": slugify(chapter["name"]),
                "chapter_index": index,
                "topic": topic,
                "topics": chapter["topics"],
                "kind": slot["kind"],
                "day": slot["day"],
                "plan": slots,
                "revise": revise,
                "query": f"{chapter['name']}{query_topic} Class {prefs['grade']} {goal_label}",
            }
        )

    return cards
