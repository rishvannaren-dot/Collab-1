from flask import Blueprint, g, redirect, render_template, url_for

from ..db import get_db
from ..services import cards as cards_service
from ..services import account, explore, plan, preferences, progress, recovery, revision, topic_info
from . import helpers
from .auth import login_required
from .topics import attach_info

bp = Blueprint("main", __name__)


def greeting_for(hour):
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


@bp.route("/welcome")
def welcome():
    if g.user is not None:
        return redirect(url_for("main.index"))
    return render_template("welcome.html")


@bp.route("/")
@login_required
def index():
    db = get_db()
    prefs = preferences.get_preferences(db, g.user["id"])
    if prefs is None:
        return redirect(url_for("onboarding.onboarding"))

    today = helpers.today()
    cards = plan.todays_cards(db, g.user["id"], prefs, cards_service.load_syllabus(), today)
    picks = explore.todays_picks(prefs["interests"], explore.load_interest_topics(), today)

    studied = progress.progress_for(db, g.user["id"])
    for card in cards:
        keys = {t: progress.topic_key(card["subject_key"], card["chapter"], t) for t in card["topics"]}
        card["studied_topics"] = {t for t, key in keys.items() if key in studied}
        if card["topic"]:
            card["topic_key"] = keys[card["topic"]]
            card["studied"] = studied.get(card["topic_key"])
        if card["kind"] == "rest":
            card["catch_up"] = [t for t in card["topics"] if t not in card["studied_topics"]]
        if card["kind"] == "review":
            card["prompts"] = {t: revision.recall_prompt(card["subject_key"], t, today) for t in card["topics"]}

    # Revise today: the student's own studied topics that are due, in their goal's subjects.
    syllabus = cards_service.load_syllabus()
    index = progress.topic_index(syllabus)
    subject_keys = cards_service.SUBJECTS_BY_GOAL.get(prefs["goal"], [])
    allowed = {key for key, info in index.items() if info["subject_key"] in subject_keys}
    due, revise_more = revision.due(db, g.user["id"], today, allowed)
    revise = [
        {
            **index[row["topic_key"]],
            "key": row["topic_key"],
            "prompt": revision.recall_prompt(index[row["topic_key"]]["subject_key"], index[row["topic_key"]]["topic"], today),
        }
        for row in due
    ]

    titles = topic_info.load_wiki_titles()
    learn_cards = [card for card in cards if card["topic"]]
    for card in learn_cards:
        card["search"] = topic_info.syllabus_search(card["topic"], card["subject"], titles)
    for pick in picks:
        pick["search"] = topic_info.interest_search(pick["article"], pick["label"])
    attach_info(learn_cards + picks)
    # Revision summaries come from the cache only, so they never slow Today down
    # or use up the live lookups.
    for item in revise:
        item["search"] = topic_info.syllabus_search(item["topic"], item["subject"], titles)
    cached = topic_info.lookup_many(db, [item["search"] for item in revise], live=0)
    for item in revise:
        item["info"] = cached.get(item["search"]["key"])

    return render_template(
        "index.html",
        prefs=prefs,
        cards=cards,
        picks=picks,
        goal_label=preferences.GOALS.get(prefs["goal"], ""),
        greeting=greeting_for(helpers.now().hour),
        today=today,
        has_recovery_key=recovery.key_created_at(db, g.user["id"]) is not None,
        finished=progress.day_finished(cards, studied, today),
        revise=revise,
        revise_more=revise_more,
    )


@bp.route("/privacy")
def privacy():
    return render_template("privacy.html", privacy_version=account.PRIVACY_VERSION)
