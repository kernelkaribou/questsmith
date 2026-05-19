from flask import Blueprint, render_template, request, redirect, url_for, session

from app import db
from app.models import (
    Member, Journey, Quest, PartyGoal, QuestLevel, QuestLevelUnlock, ShopItem,
    AchievementUnlock, Achievement, ActivityLog,
)
from app.engines import ledger, validation, side_quest as side_quest_engine, quest as quest_engine, lifetime

bp = Blueprint("dashboard", __name__, url_prefix="/")


@bp.route("/")
def index():
    """Member selection screen."""
    members = Member.query.all()
    return render_template("dashboard/index.html", members=members)


@bp.route("/quest/<int:quest_id>")
def quest_view(quest_id):
    """Main quest dashboard."""
    quest = db.session.get(Quest, quest_id)
    journey = quest.journey
    member = quest.member
    is_admin = session.get("admin", False)

    balance = ledger.get_balance(quest_id)
    total_earned = ledger.get_lifetime_earned(quest_id)

    # Party Goals progress (only if quest is in a journey)
    goal_progress = []
    if journey:
        party_goals = PartyGoal.query.filter_by(journey_id=journey.id).order_by(PartyGoal.sort_order).all()
        journey_totals = ledger.get_journey_totals(journey.id)
        combined_total = sum(journey_totals.values())
        for goal in party_goals:
            goal_progress.append({
                "goal": goal,
                "current": combined_total,
                "percent": min(100, int(combined_total / goal.target_amount * 100)) if goal.target_amount else 0,
            })

    # Quest Levels (belong to quest now)
    levels = QuestLevel.query.filter_by(quest_id=quest_id).order_by(QuestLevel.threshold).all()
    unlocked_levels = validation.get_unlocked_levels(quest_id)

    # Check for new level unlocks (only relevant if admin just logged)
    from app.engines.validation import check_level_unlocks
    new_level_unlocks = check_level_unlocks(quest_id)
    if new_level_unlocks:
        db.session.commit()

    # Combined Shop: quest-owned + journey-owned
    shop_items = ShopItem.query.filter_by(quest_id=quest_id).order_by(ShopItem.sort_order).all()
    if journey:
        journey_shop = ShopItem.query.filter_by(journey_id=journey.id).order_by(ShopItem.sort_order).all()
        shop_items = shop_items + journey_shop

    # Side quests (belong to quest now)
    sq_data = side_quest_engine.get_available_side_quests(quest_id)
    sq_status = [{"quest": item["side_quest"], "available": item["can_complete"]} for item in sq_data]

    # Quest chains
    chain_data = side_quest_engine.get_available_chains(quest_id)

    # Achievements for this member
    unlocks = AchievementUnlock.query.filter_by(member_id=member.id).all()
    achievements = [db.session.get(Achievement, u.achievement_id) for u in unlocks]

    # Activity timeline (recent 20)
    recent_logs = ActivityLog.query.filter_by(quest_id=quest_id).order_by(ActivityLog.logged_at.desc()).limit(20).all()

    # Earning progress (units toward next currency)
    earning_progress = quest_engine.get_earning_progress(quest_id)

    # Theme context
    ctx = quest_engine.get_quest_context(quest_id)

    return render_template(
        "dashboard/quest.html",
        quest=quest,
        journey=journey,
        member=member,
        balance=balance,
        total_earned=total_earned,
        goal_progress=goal_progress,
        levels=levels,
        unlocked_levels=unlocked_levels,
        shop_items=shop_items,
        sq_status=sq_status,
        chain_data=chain_data,
        earning_progress=earning_progress,
        achievements=achievements,
        recent_logs=recent_logs,
        ctx=ctx,
        is_admin=is_admin,
    )


@bp.route("/member/<int:member_id>")
def member_select(member_id):
    """Show active quests for a member to pick."""
    member = db.session.get(Member, member_id)
    quests = Quest.query.filter_by(member_id=member_id, status="active").all()
    if len(quests) == 1:
        return redirect(url_for("dashboard.quest_view", quest_id=quests[0].id))
    return render_template("dashboard/member_select.html", member=member, quests=quests)


@bp.route("/member/<int:member_id>/profile")
def member_profile(member_id):
    """Lifetime stats and achievement showcase for a member."""
    member = db.session.get(Member, member_id)
    stats = lifetime.get_all_stats(member_id)

    unlocks = AchievementUnlock.query.filter_by(member_id=member_id).order_by(AchievementUnlock.unlocked_at.desc()).all()
    achievements = []
    for u in unlocks:
        ach = db.session.get(Achievement, u.achievement_id)
        achievements.append({"achievement": ach, "unlocked_at": u.unlocked_at})

    all_quests = Quest.query.filter_by(member_id=member_id).order_by(Quest.created_at.desc()).all()

    return render_template(
        "dashboard/profile.html",
        member=member,
        stats=stats,
        achievements=achievements,
        all_quests=all_quests,
    )


@bp.route("/quest/<int:quest_id>/history")
def quest_history(quest_id):
    """Activity log timeline for a specific quest."""
    quest = db.session.get(Quest, quest_id)
    logs = ActivityLog.query.filter_by(quest_id=quest_id).order_by(ActivityLog.logged_at.desc()).all()
    ctx = quest_engine.get_quest_context(quest_id)
    return render_template(
        "dashboard/history.html",
        quest=quest,
        logs=logs,
        ctx=ctx,
    )
