from datetime import date

from focusfeed.services import explore

TOPICS = {"sports": ["Cricket", "Athletics (sport)", "Chess"], "music": ["Raga", "Rhythm"]}


def test_display_name_hides_brackets():
    assert explore.display_name("Athletics (sport)") == "Athletics"
    assert explore.display_name("Cricket") == "Cricket"


def test_one_pick_per_followed_interest():
    picks = explore.todays_picks(["sports", "music", "not-real"], TOPICS, date(2026, 10, 17))
    assert [p["key"] for p in picks] == ["sports", "music"]
    assert picks[0]["label"] == "Sports"
    assert picks[0]["article"] in TOPICS["sports"]
    assert picks[0]["name"] == explore.display_name(picks[0]["article"])


def test_picks_are_stable_within_a_day_and_change_the_next():
    day = date(2026, 10, 17)
    first = explore.todays_picks(["sports"], TOPICS, day)
    assert first == explore.todays_picks(["sports"], TOPICS, day)
    tomorrow = explore.todays_picks(["sports"], TOPICS, date(2026, 10, 18))
    assert first[0]["article"] != tomorrow[0]["article"]
