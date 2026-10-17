"""The study record: topics a student marked as studied and how sure they felt.

Only dates are stored (no times or durations), one row per topic.
"""

from .cards import grade_chapters, slugify

CONFIDENCE = {3: "Got it", 2: "Shaky", 1: "Lost me"}


def topic_key(subject_key, chapter_name, topic):
    """"physics/electrostatics/coulomb-s-law": stable as long as the names don't change."""
    return f"{subject_key}/{slugify(chapter_name)}/{slugify(topic)}"


def topic_index(syllabus):
    """{topic_key: details} for every topic in the syllabus."""
    index = {}
    for subject_key, subject in syllabus["subjects"].items():
        for chapter in subject["chapters"]:
            for topic in chapter["topics"]:
                index[topic_key(subject_key, chapter["name"], topic)] = {
                    "subject_key": subject_key,
                    "subject": subject["label"],
                    "chapter": chapter["name"],
                    "chapter_slug": slugify(chapter["name"]),
                    "grade": chapter["grade"],
                    "topic": topic,
                    "anchor": slugify(topic),
                }
    return index


def valid_key(syllabus, key):
    return key in topic_index(syllabus)


def mark(db, user_id, key, confidence, today, schedule=None):
    """Record that the topic was studied today. Marking again updates it.

    `schedule` is the (box, due_on) for revision; re-marking restarts it.
    """
    box, due_on = schedule or (0, None)
    db.execute(
        "INSERT INTO topic_progress"
        " (user_id, topic_key, confidence, first_studied_on, last_studied_on, box, due_on)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(user_id, topic_key) DO UPDATE SET"
        " confidence = excluded.confidence, last_studied_on = excluded.last_studied_on,"
        " box = excluded.box, due_on = excluded.due_on",
        (
            user_id,
            key,
            confidence,
            today.isoformat(),
            today.isoformat(),
            box,
            due_on.isoformat() if due_on else None,
        ),
    )
    db.commit()


def unmark(db, user_id, key):
    db.execute("DELETE FROM topic_progress WHERE user_id = ? AND topic_key = ?", (user_id, key))
    db.commit()


def progress_for(db, user_id):
    """{topic_key: row as a dict} for everything the user has marked."""
    rows = db.execute("SELECT * FROM topic_progress WHERE user_id = ?", (user_id,)).fetchall()
    return {row["topic_key"]: dict(row) for row in rows}


def coverage(syllabus, subject_keys, grade, studied):
    """Per subject and chapter: how many topics are marked, out of how many."""
    subjects = []
    for subject_key in subject_keys:
        chapters = []
        for chapter in grade_chapters(syllabus, subject_key, grade):
            topics = []
            for topic in chapter["topics"]:
                key = topic_key(subject_key, chapter["name"], topic)
                row = studied.get(key)
                topics.append(
                    {
                        "name": topic,
                        "key": key,
                        "anchor": slugify(topic),
                        "confidence": row["confidence"] if row else None,
                    }
                )
            chapters.append(
                {
                    "name": chapter["name"],
                    "slug": slugify(chapter["name"]),
                    "done": sum(1 for t in topics if t["confidence"]),
                    "total": len(topics),
                    "topics": topics,
                }
            )
        if not chapters:
            continue
        subjects.append(
            {
                "key": subject_key,
                "label": syllabus["subjects"][subject_key]["label"],
                "done": sum(c["done"] for c in chapters),
                "total": sum(c["total"] for c in chapters),
                "chapters": chapters,
            }
        )
    return subjects


def needs_work(syllabus, studied, subject_keys, grade, limit=10):
    """Topics marked Shaky or Lost me, least sure and longest ago first."""
    index = topic_index(syllabus)
    items = []
    for key, row in studied.items():
        info = index.get(key)
        if info is None or info["subject_key"] not in subject_keys or info["grade"] != grade:
            continue
        if row["confidence"] <= 2:
            items.append({**info, "key": key, "confidence": row["confidence"], "last": row["last_studied_on"]})
    items.sort(key=lambda item: (item["confidence"], item["last"]))
    return items[:limit]


def day_finished(cards, studied, today, revise_due=()):
    """True when there was something to learn today, every one is marked today, and
    nothing else is waiting: no revision due and no review or practice day open."""
    learn = [card for card in cards if card["kind"] == "learn"]
    if not learn or revise_due:
        return False
    if any(card["kind"] in ("review", "practice") for card in cards):
        return False
    today_iso = today.isoformat()
    return all(
        studied.get(card["topic_key"], {}).get("last_studied_on") == today_iso for card in learn
    )
