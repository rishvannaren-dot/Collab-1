"""Each student's week plan: which chapter each subject is on, and since when."""

from datetime import date

from .cards import build_cards


def get_plans(db, user_id):
    """{subject_key: {"chapter_index": int, "start_on": date}} for the user."""
    rows = db.execute(
        "SELECT subject_key, chapter_index, start_on FROM study_plan WHERE user_id = ?", (user_id,)
    ).fetchall()
    return {
        row["subject_key"]: {
            "chapter_index": row["chapter_index"],
            "start_on": date.fromisoformat(row["start_on"]),
        }
        for row in rows
    }


def start_chapter(db, user_id, subject_key, chapter_index, today):
    """Make `chapter_index` this subject's chapter, with day 1 today."""
    db.execute(
        "INSERT INTO study_plan (user_id, subject_key, chapter_index, start_on) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, subject_key) DO UPDATE SET "
        "chapter_index = excluded.chapter_index, start_on = excluded.start_on",
        (user_id, subject_key, chapter_index, today.isoformat()),
    )
    db.commit()


def reset_plans(db, user_id, subject_keys, today):
    """Start every subject at the grade's first chapter today (after a grade or goal change)."""
    db.execute("DELETE FROM study_plan WHERE user_id = ?", (user_id,))
    db.executemany(
        "INSERT INTO study_plan (user_id, subject_key, chapter_index, start_on) VALUES (?, ?, 0, ?)",
        [(user_id, key, today.isoformat()) for key in subject_keys],
    )
    db.commit()


def todays_cards(db, user_id, prefs, syllabus, today):
    return build_cards(prefs, syllabus, today, get_plans(db, user_id))
