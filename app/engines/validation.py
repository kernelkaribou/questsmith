"""Validation Engine: Party goal fairness checks and quest level unlock logic."""
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app import db
from app.models import PartyGoal, QuestLevel, QuestLevelUnlock, Quest, Transaction
from app.engines.ledger import get_campaign_totals, get_lifetime_earned


def check_party_goal(goal):
    """
    Check if a party goal is unlocked.
    Returns dict with status and details.
    """
    if goal.unlocked_at:
        return {"unlocked": True, "unlocked_at": goal.unlocked_at}

    member_totals = get_campaign_totals(goal.campaign_id)
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
    all_quests = Quest.query.filter_by(campaign_id=goal.campaign_id).all()
    for quest in all_quests:
        if quest.member_id not in member_totals:
            meets_min = goal.min_individual_contribution == 0
            if not meets_min:
                all_fair = False
            fairness_details.append({
                "member_id": quest.member_id,
                "earned": 0,
                "required": goal.min_individual_contribution,
                "meets_minimum": meets_min,
                "shortfall": max(0, goal.min_individual_contribution),
            })

    unlocked = volume_met and all_fair

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


def check_all_party_goals(campaign_id):
    """Check all party goals for a campaign."""
    goals = PartyGoal.query.filter_by(campaign_id=campaign_id).order_by(PartyGoal.sort_order).all()
    return [{"goal": goal, **check_party_goal(goal)} for goal in goals]


def get_unlocked_levels(quest_id):
    """Get which quest levels a quest has unlocked based on lifetime earned."""
    quest = db.session.get(Quest, quest_id)
    if not quest:
        return []

    lifetime_earned = get_lifetime_earned(quest_id)
    levels = QuestLevel.query.filter_by(quest_id=quest_id).order_by(
        QuestLevel.threshold
    ).all()

    # Look up persisted unlock timestamps
    existing_unlocks = {
        u.quest_level_id: u.unlocked_at
        for u in QuestLevelUnlock.query.filter_by(quest_id=quest_id).all()
    }

    return [
        {
            "level": level,
            "unlocked": lifetime_earned >= level.threshold,
            "progress": lifetime_earned,
            "unlocked_at": existing_unlocks.get(level.id),
        }
        for level in levels
    ]


def check_level_unlocks(quest_id):
    """Persist any newly unlocked levels. Returns list of newly unlocked QuestLevelUnlock."""
    lifetime_earned = get_lifetime_earned(quest_id)
    levels = QuestLevel.query.filter_by(quest_id=quest_id).all()
    new_unlocks = []

    for level in levels:
        if lifetime_earned >= level.threshold:
            existing = QuestLevelUnlock.query.filter_by(
                quest_id=quest_id, quest_level_id=level.id
            ).first()
            if not existing:
                unlock = QuestLevelUnlock(quest_id=quest_id, quest_level_id=level.id)
                db.session.add(unlock)
                try:
                    db.session.flush()
                    new_unlocks.append(unlock)
                except IntegrityError:
                    db.session.rollback()

    return new_unlocks
