from flask import Blueprint, render_template, request, redirect, url_for

from app import db
from app.models import (
    Member, Journey, Quest, CoOpGoal, PrizeTier, PrizeItem,
    SideQuest, AchievementUnlock, Achievement,
)
from app.engines import ledger, validation, side_quest as side_quest_engine, quest as quest_engine

bp = Blueprint("dashboard", __name__, url_prefix="/")


@bp.route("/")
def index():
    """Member selection screen."""
    members = Member.query.all()
    return render_template("dashboard/index.html", members=members)


@bp.route("/quest/<int:quest_id>")
def quest_view(quest_id):
    """Main quest dashboard for a member within a journey."""
    quest = db.session.get(Quest, quest_id)
    journey = quest.journey
    member = quest.member

    balance = ledger.get_balance(quest_id)
    total_earned = ledger.get_lifetime_earned(quest_id)

    # Co-Op progress
    coop_goals = CoOpGoal.query.filter_by(journey_id=journey.id).order_by(CoOpGoal.sort_order).all()
    journey_totals = ledger.get_journey_totals(journey.id)
    coop_progress = []
    for goal in coop_goals:
        coop_progress.append({
            "goal": goal,
            "current": journey_totals,
            "percent": min(100, int(journey_totals / goal.target_amount * 100)) if goal.target_amount else 0,
        })

    # Prize tiers
    tiers = PrizeTier.query.filter_by(journey_id=journey.id).order_by(PrizeTier.sort_order).all()
    unlocked_tiers = validation.get_unlocked_tiers(quest_id)

    # Prize shop
    prizes = PrizeItem.query.filter_by(journey_id=journey.id).order_by(PrizeItem.sort_order).all()

    # Side quests
    side_quests = SideQuest.query.filter_by(journey_id=journey.id).order_by(SideQuest.sort_order).all()
    sq_status = []
    for sq in side_quests:
        available = side_quest_engine.is_available(sq.id, quest_id)
        sq_status.append({"quest": sq, "available": available})

    # Achievements for this member
    unlocks = AchievementUnlock.query.filter_by(member_id=member.id).all()
    achievements = [db.session.get(Achievement, u.achievement_id) for u in unlocks]

    # Theme context
    ctx = quest_engine.get_quest_context(quest_id)

    return render_template(
        "dashboard/quest.html",
        quest=quest,
        journey=journey,
        member=member,
        balance=balance,
        total_earned=total_earned,
        coop_progress=coop_progress,
        tiers=tiers,
        unlocked_tiers=unlocked_tiers,
        prizes=prizes,
        sq_status=sq_status,
        achievements=achievements,
        ctx=ctx,
    )


@bp.route("/member/<int:member_id>")
def member_select(member_id):
    """Show active quests for a member to pick which journey to enter."""
    member = db.session.get(Member, member_id)
    quests = Quest.query.filter_by(member_id=member_id).join(Journey).filter(Journey.status == "active").all()
    if len(quests) == 1:
        return redirect(url_for("dashboard.quest_view", quest_id=quests[0].id))
    return render_template("dashboard/member_select.html", member=member, quests=quests)
