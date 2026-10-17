INTERESTS = {
    "science-tech": "Science & Technology",
    "education": "Education & Exam Prep",
    "sports": "Sports",
    "arts": "Arts & Design",
    "music": "Music",
    "history": "History & Culture",
    "business": "Business & Money",
    "health": "Health & Fitness",
}

GRADES = list(range(6, 13))

GOALS = {
    "jee": "JEE",
    "neet": "NEET",
    "boards": "Board exams",
    "general": "General learning",
}


def get_preferences(db, user_id):
    """Return the user's saved preferences as a dict, or None if not set yet."""
    row = db.execute(
        "SELECT interests, grade, goal FROM preferences WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row is None:
        return None
    return {
        "interests": [i for i in row["interests"].split(",") if i],
        "grade": row["grade"],
        "goal": row["goal"],
    }


def validate_preferences(interests, grade, goal):
    """Return (cleaned values, error message). The error is None when valid."""
    interests = [i for i in interests if i in INTERESTS]
    if not interests:
        return None, "Pick at least one interest."
    try:
        grade = int(grade)
    except (TypeError, ValueError):
        return None, "Pick your grade."
    if grade not in GRADES:
        return None, "Pick your grade."
    if goal not in GOALS:
        return None, "Pick a goal."
    return {"interests": interests, "grade": grade, "goal": goal}, None


def save_preferences(db, user_id, prefs):
    db.execute(
        "INSERT INTO preferences (user_id, interests, grade, goal) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET "
        "interests = excluded.interests, grade = excluded.grade, goal = excluded.goal",
        (user_id, ",".join(prefs["interests"]), prefs["grade"], prefs["goal"]),
    )
    db.commit()
