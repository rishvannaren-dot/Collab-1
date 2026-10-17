from datetime import date

from focusfeed.services import cards


def prefs(goal="jee", grade=12, interests=("education",)):
    return {"interests": list(interests), "grade": grade, "goal": goal}


def test_jee_gets_three_subjects():
    result = cards.build_cards(prefs("jee"), cards.load_syllabus(), date(2026, 10, 17))
    assert [c["subject"] for c in result] == ["Physics", "Chemistry", "Maths"]


def test_neet_gets_biology_not_maths():
    result = cards.build_cards(prefs("neet"), cards.load_syllabus(), date(2026, 10, 17))
    assert [c["subject"] for c in result] == ["Physics", "Chemistry", "Biology"]


def test_cards_match_grade():
    syllabus = cards.load_syllabus()
    grade_12 = {c["name"] for c in syllabus["subjects"]["physics"]["chapters"] if c["grade"] == 12}
    result = cards.build_cards(prefs("jee", grade=12), syllabus, date(2026, 10, 17))
    assert result[0]["chapter"] in grade_12


def test_card_topic_belongs_to_chapter_and_query_names_it():
    card = cards.build_cards(prefs("jee"), cards.load_syllabus(), date(2026, 10, 17))[0]
    assert card["topic"] in card["topics"]
    assert card["topic"] in card["query"]
    assert "Class 12" in card["query"]


def test_same_day_is_stable_and_topic_changes_next_day():
    syllabus = cards.load_syllabus()
    a = cards.build_cards(prefs(), syllabus, date(2026, 10, 17))
    b = cards.build_cards(prefs(), syllabus, date(2026, 10, 17))
    c = cards.build_cards(prefs(), syllabus, date(2026, 10, 18))
    assert a == b
    assert a[0]["topic"] != c[0]["topic"] or a[0]["chapter"] != c[0]["chapter"]


def test_no_cards_for_general_goal_or_young_grade():
    syllabus = cards.load_syllabus()
    assert cards.build_cards(prefs("general"), syllabus, date(2026, 10, 17)) == []
    assert cards.build_cards(prefs("jee", grade=8), syllabus, date(2026, 10, 17)) == []
