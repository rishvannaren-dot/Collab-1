"""Things to explore for each interest, with one pick per day."""

import json
import re
from pathlib import Path

from .preferences import INTERESTS

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_interest_topics():
    with open(DATA_DIR / "interests.json", encoding="utf-8") as f:
        return json.load(f)["topics"]


def display_name(article):
    """"Athletics (sport)" -> "Athletics"."""
    return re.sub(r"\s*\([^)]*\)$", "", article)


def todays_picks(interest_keys, topics_by_interest, today):
    """One article per followed interest, changing daily and stable within a day."""
    day = today.toordinal()
    picks = []
    for number, key in enumerate(interest_keys):
        articles = topics_by_interest.get(key)
        if key not in INTERESTS or not articles:
            continue
        # Offset by position so two interests don't move in lockstep.
        article = articles[(day + number) % len(articles)]
        picks.append(
            {"key": key, "label": INTERESTS[key], "article": article, "name": display_name(article)}
        )
    return picks
