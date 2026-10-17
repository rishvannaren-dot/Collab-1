from datetime import date, timedelta

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
    card = cards.build_cards(prefs("jee"), cards.load_syllabus(), date(2026, 10, 20))[0]
    assert card["topic"] in card["topics"]
    assert card["topic"] in card["query"]
    assert "Class 12" in card["query"]


def test_same_day_is_stable_and_topic_changes_next_day():
    syllabus = cards.load_syllabus()
    a = cards.build_cards(prefs(), syllabus, date(2026, 10, 20))
    b = cards.build_cards(prefs(), syllabus, date(2026, 10, 20))
    c = cards.build_cards(prefs(), syllabus, date(2026, 10, 21))
    assert a == b
    assert a[0]["topic"] != c[0]["topic"]


def test_slugify():
    assert cards.slugify("Work, Energy and Power") == "work-energy-and-power"
    assert cards.slugify("Cell: The Unit of Life") == "cell-the-unit-of-life"
    assert cards.slugify("Newton's three laws") == "newton-s-three-laws"


def test_card_links_back_to_its_chapter():
    syllabus = cards.load_syllabus()
    card = cards.build_cards(prefs("jee"), syllabus, date(2026, 10, 17))[0]
    subject, chapter = cards.find_chapter(syllabus, card["subject_key"], card["slug"])
    assert subject["label"] == card["subject"]
    assert chapter["name"] == card["chapter"]


def test_find_chapter_unknown():
    syllabus = cards.load_syllabus()
    assert cards.find_chapter(syllabus, "physics", "no-such-chapter") is None
    assert cards.find_chapter(syllabus, "astrology", "electrostatics") is None


def test_no_cards_for_general_goal_or_young_grade():
    syllabus = cards.load_syllabus()
    assert cards.build_cards(prefs("general"), syllabus, date(2026, 10, 17)) == []
    assert cards.build_cards(prefs("jee", grade=8), syllabus, date(2026, 10, 17)) == []


# Week plans


def all_chapters():
    syllabus = cards.load_syllabus()
    return [(key, c) for key, s in syllabus["subjects"].items() for c in s["chapters"]]


def test_every_chapter_week_teaches_each_topic_once_in_order():
    for _, chapter in all_chapters():
        slots = cards.week_slots(chapter["topics"])
        assert [s["day"] for s in slots] == [1, 2, 3, 4, 5, 6, 7]
        assert [s["topic"] for s in slots if s["kind"] == "learn"] == chapter["topics"]
        assert slots[-1]["kind"] == "rest"


def test_week_shapes_for_four_and_five_topics():
    kinds = lambda n: [s["kind"] for s in cards.week_slots([f"t{i}" for i in range(n)])]
    assert kinds(4) == ["learn"] * 4 + ["review", "practice", "rest"]
    assert kinds(5) == ["learn"] * 5 + ["review", "rest"]
    assert kinds(3) == ["learn"] * 3 + ["review", "practice", "practice", "rest"]


def test_syllabus_chapters_fit_in_a_week_and_have_unique_slugs():
    syllabus = cards.load_syllabus()
    for subject in syllabus["subjects"].values():
        slugs = [cards.slugify(c["name"]) for c in subject["chapters"]]
        assert len(slugs) == len(set(slugs))
        for chapter in subject["chapters"]:
            assert 1 <= len(chapter["topics"]) <= 5, chapter["name"]


def test_plan_position():
    start = date(2026, 10, 20)
    assert cards.plan_position(0, start, start, 7) == (0, 0, 0)
    assert cards.plan_position(0, start, start + timedelta(days=6), 7) == (0, 6, 0)
    assert cards.plan_position(0, start, start + timedelta(days=7), 7) == (1, 0, 1)
    assert cards.plan_position(5, start, start + timedelta(days=14), 7) == (0, 0, 2)  # wraps
    assert cards.plan_position(0, start, start - timedelta(days=3), 7) == (0, 0, 0)  # future start


def plan(index=1, start=date(2026, 10, 20)):
    return {"physics": {"chapter_index": index, "start_on": start}}


def physics_card(day, plans):
    return cards.build_cards(prefs("jee"), cards.load_syllabus(), day, plans)[0]


def test_a_plan_starts_at_topic_one_and_moves_through_the_week():
    card = physics_card(date(2026, 10, 20), plan())
    assert card["chapter"] == "Current Electricity"
    assert card["topic"] == "Ohm's law and resistivity"
    assert (card["kind"], card["day"], card["revise"]) == ("learn", 1, None)

    assert physics_card(date(2026, 10, 24), plan())["kind"] == "review"
    assert physics_card(date(2026, 10, 25), plan())["kind"] == "practice"
    rest = physics_card(date(2026, 10, 26), plan())
    assert rest["kind"] == "rest" and rest["topic"] is None
    assert "None" not in rest["query"]

    next_week = physics_card(date(2026, 10, 27), plan())
    assert next_week["chapter"] == "Magnetic Effects of Current"
    assert next_week["topic"] == "Biot-Savart law"
    assert next_week["revise"] == "Current Electricity"


def test_without_a_plan_chapters_run_monday_to_sunday():
    monday = date(2026, 10, 19)
    card = physics_card(monday, None)
    assert card["day"] == 1
    assert card["topic"] == card["topics"][0]
    assert physics_card(monday + timedelta(days=6), None)["chapter"] == card["chapter"]
    assert physics_card(monday + timedelta(days=7), None)["chapter"] != card["chapter"]
