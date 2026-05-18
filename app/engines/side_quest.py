"""Side Quest Engine: Track completions, enforce cooldowns, award currency."""
from datetime import datetime, timezone, timedelta

from app import db
from app.models import SideQuest, SideQuestCompletion, Quest
from app.engines.ledger import record_side_quest_reward


def get_available_side_quests(quest_id):
    """Get side quests available for a quest's member, with completion status."""
    quest = db.session.get(Quest, quest_id)
    if not quest:
        return []

    side_quests = SideQuest.query.filter_by(
        journey_id=quest.journey_id, is_active=True
    ).order_by(SideQuest.sort_order).all()

    result = []
    for sq in side_quests:
        status = _get_completion_status(sq, quest_id)
        result.append({
            "side_quest": sq,
            "can_complete": status["can_complete"],
            "last_completed": status["last_completed"],
            "cooldown_until": status["cooldown_until"],
            "total_completions": status["total_completions"],
        })

    return result


def complete_side_quest(side_quest_id, quest_id):
    """
    Complete a side quest for a member (identified by quest_id).
    Returns the completion and transaction, or None if not available.
    """
    side_quest = db.session.get(SideQuest, side_quest_id)
    quest = db.session.get(Quest, quest_id)

    if not side_quest or not quest:
        return None
    if side_quest.journey_id != quest.journey_id:
        return None

    status = _get_completion_status(side_quest, quest_id)
    if not status["can_complete"]:
        return None

    # Record completion
    completion = SideQuestCompletion(
        side_quest_id=side_quest_id,
        quest_id=quest_id,
    )
    db.session.add(completion)

    # Award currency
    txn = record_side_quest_reward(
        quest_id=quest_id,
        amount=side_quest.currency_reward,
        description=f"Side quest: {side_quest.name}",
    )

    return {"completion": completion, "transaction": txn}


def _get_completion_status(side_quest, quest_id):
    """Determine if a side quest can be completed right now."""
    completions = SideQuestCompletion.query.filter_by(
        side_quest_id=side_quest.id, quest_id=quest_id
    ).order_by(SideQuestCompletion.completed_at.desc()).all()

    total = len(completions)
    last_completed = completions[0].completed_at if completions else None
    now = datetime.now(timezone.utc)

    # Normalize to UTC-aware if SQLite returns naive datetime
    if last_completed and last_completed.tzinfo is None:
        last_completed = last_completed.replace(tzinfo=timezone.utc)

    if side_quest.repeat_type == "one_time":
        return {
            "can_complete": total == 0,
            "last_completed": last_completed,
            "cooldown_until": None,
            "total_completions": total,
        }

    elif side_quest.repeat_type == "daily":
        if not last_completed:
            cooldown_until = None
            can_complete = True
        else:
            cooldown_until = last_completed.replace(
                hour=0, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)
            can_complete = now >= cooldown_until
        return {
            "can_complete": can_complete,
            "last_completed": last_completed,
            "cooldown_until": cooldown_until if not can_complete else None,
            "total_completions": total,
        }

    elif side_quest.repeat_type == "weekly":
        if not last_completed:
            cooldown_until = None
            can_complete = True
        else:
            days_since_monday = last_completed.weekday()
            week_start = last_completed.replace(
                hour=0, minute=0, second=0, microsecond=0
            ) - timedelta(days=days_since_monday)
            cooldown_until = week_start + timedelta(weeks=1)
            can_complete = now >= cooldown_until
        return {
            "can_complete": can_complete,
            "last_completed": last_completed,
            "cooldown_until": cooldown_until if not can_complete else None,
            "total_completions": total,
        }

    return {"can_complete": False, "last_completed": last_completed, "cooldown_until": None, "total_completions": total}
