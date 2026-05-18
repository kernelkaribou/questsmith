"""Validation Engine: Co-Op goal fairness checks and prize tier unlock logic."""
from datetime import datetime, timezone

from app import db
from app.models import CoOpGoal, PrizeTier, Quest, Transaction
from app.engines.ledger import get_journey_totals, get_lifetime_earned


def check_coop_goal(goal):
    """
    Check if a Co-Op goal is unlocked.
    Returns dict with status and details.
    """
    if goal.unlocked_at:
        return {"unlocked": True, "unlocked_at": goal.unlocked_at}

    member_totals = get_journey_totals(goal.journey_id)
    combined_total = sum(member_totals.values())

    # Volume check
    volume_met = combined_total >= goal.target_amount

    # Fairness check
    fairness_details = []
    all_fair = True
    for member_id, earned in member_totals.items():
        meets_minimum = earned >= goal.min_individual_contribution
        if not meets_minimum:
            all_fair = False
        fairness_details.append({
            "member_id": member_id,
            "earned": earned,
            "required": goal.min_individual_contribution,
            "meets_minimum": meets_minimum,
            "shortfall": max(0, goal.min_individual_contribution - earned),
        })

    # Also check members with zero contributions (no transactions yet)
    all_quests = Quest.query.filter_by(journey_id=goal.journey_id).all()
    for quest in all_quests:
        if quest.member_id not in member_totals:
            all_fair = False
            fairness_details.append({
                "member_id": quest.member_id,
                "earned": 0,
                "required": goal.min_individual_contribution,
                "meets_minimum": goal.min_individual_contribution == 0,
                "shortfall": goal.min_individual_contribution,
            })

    unlocked = volume_met and all_fair

    # Persist unlock if newly achieved
    if unlocked and not goal.unlocked_at:
        goal.unlocked_at = datetime.now(timezone.utc)
        db.session.add(goal)

    return {
        "unlocked": unlocked,
        "unlocked_at": goal.unlocked_at,
        "combined_total": combined_total,
        "target_amount": goal.target_amount,
        "volume_met": volume_met,
        "all_fair": all_fair,
        "fairness_details": fairness_details,
    }


def check_all_coop_goals(journey_id):
    """Check all Co-Op goals for a journey."""
    goals = CoOpGoal.query.filter_by(journey_id=journey_id).order_by(CoOpGoal.sort_order).all()
    return [{"goal": goal, **check_coop_goal(goal)} for goal in goals]


def get_unlocked_tiers(quest_id):
    """Get which prize tiers a quest has unlocked based on lifetime earned."""
    quest = db.session.get(Quest, quest_id)
    if not quest:
        return []

    lifetime_earned = get_lifetime_earned(quest_id)
    tiers = PrizeTier.query.filter_by(journey_id=quest.journey_id).order_by(
        PrizeTier.sort_order
    ).all()

    return [
        {"tier": tier, "unlocked": lifetime_earned >= tier.threshold, "progress": lifetime_earned}
        for tier in tiers
    ]
