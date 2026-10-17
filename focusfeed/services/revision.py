"""Spaced revision: studied topics come back after growing gaps.

Each topic sits in a "box" from 0 to 5. Remembering it moves it up a box, and
the next review is INTERVALS[box] days later; forgetting sends it back to box 0
for tomorrow. Recall is self-rated: there is no question bank and no AI.
"""

from datetime import date, timedelta

INTERVALS = [1, 3, 7, 14, 30, 60]  # days until the next review, by box
MAX_BOX = len(INTERVALS) - 1
DAILY_LIMIT = 5

# Two prompts per subject; one is picked per day so they alternate.
RECALL_PROMPTS = {
    "physics": [
        "Write the law or formula for {topic} and the SI unit of each quantity, then check.",
        "Explain {topic} to a friend in three sentences with one example.",
    ],
    "chemistry": [
        "Explain {topic} in two sentences with one example.",
        "Write one equation or structure that shows {topic}.",
    ],
    "maths": [
        "Solve one textbook example on {topic} without looking.",
        "Write the key formula for {topic} and when to use it.",
    ],
    "biology": [
        "Draw and label a diagram for {topic} from memory.",
        "List the steps or parts of {topic} in order.",
    ],
}
DEFAULT_PROMPTS = ["Say or write what you remember about {topic}, then check."]


def schedule_first(confidence, today):
    """(box, due date) after first marking a topic: sure topics wait longer."""
    if confidence == 3:
        return 1, today + timedelta(days=INTERVALS[1])
    return 0, today + timedelta(days=INTERVALS[0])


def after_review(box, remembered, today):
    if not remembered:
        return 0, today + timedelta(days=INTERVALS[0])
    box = min(box + 1, MAX_BOX)
    return box, today + timedelta(days=INTERVALS[box])


def due(db, user_id, today, allowed_keys, limit=DAILY_LIMIT):
    """(topics due for review today, whether more are waiting), oldest first.

    Only keys in `allowed_keys` count, so subjects the student no longer takes
    (or topics renamed away) stay hidden without deleting their history.
    """
    rows = db.execute(
        "SELECT topic_key, box, due_on, confidence FROM topic_progress"
        " WHERE user_id = ? AND due_on IS NOT NULL AND due_on <= ?",
        (user_id, today.isoformat()),
    ).fetchall()
    items = sorted(
        (dict(row) for row in rows if row["topic_key"] in allowed_keys),
        key=lambda row: (row["due_on"], row["box"]),
    )
    return items[:limit], len(items) > limit


def record_review(db, user_id, key, remembered, today):
    """Move the topic's box and due date. Returns False if the user never studied it."""
    row = db.execute(
        "SELECT box, confidence FROM topic_progress WHERE user_id = ? AND topic_key = ?",
        (user_id, key),
    ).fetchone()
    if row is None:
        return False
    box, due_on = after_review(row["box"], remembered, today)
    confidence = row["confidence"] if remembered else min(row["confidence"], 2)
    db.execute(
        "UPDATE topic_progress SET box = ?, due_on = ?, last_studied_on = ?, confidence = ?"
        " WHERE user_id = ? AND topic_key = ?",
        (box, due_on.isoformat(), today.isoformat(), confidence, user_id, key),
    )
    db.commit()
    return True


def recall_prompt(subject_key, topic, today):
    prompts = RECALL_PROMPTS.get(subject_key, DEFAULT_PROMPTS)
    return prompts[today.toordinal() % len(prompts)].format(topic=topic)


def as_date(value):
    return date.fromisoformat(value) if value else None
