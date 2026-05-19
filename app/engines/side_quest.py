"""Side Quest Engine: Track completions, enforce cooldowns, handle chains."""
from datetime import datetime, timezone, timedelta

from app import db
from app.models import SideQuest, SideQuestChain, SideQuestCompletion, Quest
from app.engines.ledger import record_side_quest_reward


def get_available_side_quests(quest_id):
    """Get standalone (non-chain) side quests available for a quest."""
    quest = db.session.get(Quest, quest_id)
    if not quest:
        return []

    now = datetime.now(timezone.utc)
    side_quests = SideQuest.query.filter_by(
        quest_id=quest_id, is_active=True, chain_id=None
    ).order_by(SideQuest.sort_order).all()

    result = []
    for sq in side_quests:
        if sq.expires_at and _is_expired(sq.expires_at, now):
            continue
        status = _get_completion_status(sq, quest_id)
        result.append({
            "side_quest": sq,
            "can_complete": status["can_complete"],
            "last_completed": status["last_completed"],
            "cooldown_until": status["cooldown_until"],
            "total_completions": status["total_completions"],
        })

    return result


def get_available_chains(quest_id):
    """Get all active, non-expired, non-completed chains for a quest."""
    quest = db.session.get(Quest, quest_id)
    if not quest:
        return []

    now = datetime.now(timezone.utc)
    chains = SideQuestChain.query.filter_by(
        quest_id=quest_id, is_active=True, completed_at=None
    ).order_by(SideQuestChain.sort_order).all()

    result = []
    for chain in chains:
        if chain.expires_at and _is_expired(chain.expires_at, now):
            continue
        result.append(get_chain_status(chain, quest_id))

    return result


def get_chain_status(chain, quest_id):
    """Get completion progress for a chain."""
    steps = chain.steps.order_by(SideQuest.chain_order).all()
    completed_ids = set()
    for step in steps:
        count = SideQuestCompletion.query.filter_by(
            side_quest_id=step.id, quest_id=quest_id
        ).count()
        if count > 0:
            completed_ids.add(step.id)

    total_steps = len(steps)
    completed_count = len(completed_ids)

    # Determine which steps are available based on visibility mode
    step_data = []
    for step in steps:
        is_done = step.id in completed_ids
        is_available = False
        is_visible = True

        if not is_done:
            if chain.visibility_mode == "checklist_any_order":
                is_available = True
            else:
                # Sequential: only the first incomplete step is available
                is_available = all(
                    s.id in completed_ids for s in steps if s.chain_order < step.chain_order
                )

        if chain.visibility_mode == "mystery_sequential" and not is_done:
            # Only show the next available step
            is_visible = is_available

        step_data.append({
            "step": step,
            "completed": is_done,
            "available": is_available,
            "visible": is_visible,
        })

    return {
        "chain": chain,
        "steps": step_data,
        "total_steps": total_steps,
        "completed_count": completed_count,
        "is_complete": completed_count == total_steps,
        "percent": int(completed_count / total_steps * 100) if total_steps else 0,
    }


def complete_side_quest(side_quest_id, quest_id):
    """
    Complete a standalone side quest.
    Returns the completion and transaction, or None if not available.
    """
    side_quest = db.session.get(SideQuest, side_quest_id)
    quest = db.session.get(Quest, quest_id)

    if not side_quest or not quest:
        return None
    if side_quest.quest_id != quest_id:
        return None
    if side_quest.is_chain_step:
        return None

    now = datetime.now(timezone.utc)
    if side_quest.expires_at and _is_expired(side_quest.expires_at, now):
        return None

    status = _get_completion_status(side_quest, quest_id)
    if not status["can_complete"]:
        return None

    completion = SideQuestCompletion(
        side_quest_id=side_quest_id,
        quest_id=quest_id,
    )
    db.session.add(completion)

    txn = None
    if side_quest.currency_reward > 0:
        txn = record_side_quest_reward(
            quest_id=quest_id,
            amount=side_quest.currency_reward,
            description=f"Side quest: {side_quest.name}",
        )

    return {"completion": completion, "transaction": txn}


def complete_chain_step(side_quest_id, quest_id):
    """
    Complete a chain step. If it's the last step, complete the chain and award reward.
    Returns dict with completion info, or None if not available.
    """
    step = db.session.get(SideQuest, side_quest_id)
    quest = db.session.get(Quest, quest_id)

    if not step or not quest:
        return None
    if not step.is_chain_step:
        return None
    if step.quest_id != quest_id:
        return None

    chain = step.chain
    if chain.completed_at is not None:
        return None

    now = datetime.now(timezone.utc)
    if chain.expires_at and _is_expired(chain.expires_at, now):
        return None

    # Check if this step is available based on visibility rules
    chain_data = get_chain_status(chain, quest_id)
    step_info = next((s for s in chain_data["steps"] if s["step"].id == step.id), None)
    if not step_info or step_info["completed"] or not step_info["available"]:
        return None

    # Record step completion
    completion = SideQuestCompletion(
        side_quest_id=side_quest_id,
        quest_id=quest_id,
    )
    db.session.add(completion)
    db.session.flush()

    # Check if chain is now complete
    txn = None
    chain_completed = False
    updated_status = get_chain_status(chain, quest_id)
    if updated_status["is_complete"]:
        chain.completed_at = now
        chain_completed = True
        if chain.currency_reward > 0:
            txn = record_side_quest_reward(
                quest_id=quest_id,
                amount=chain.currency_reward,
                description=f"Chain complete: {chain.name}",
            )

    return {
        "completion": completion,
        "transaction": txn,
        "chain_completed": chain_completed,
        "chain": chain,
    }


def _is_expired(expires_at, now):
    """Check if a datetime has passed."""
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return now >= expires_at


def _get_completion_status(side_quest, quest_id):
    """Determine if a standalone side quest can be completed right now."""
    completions = SideQuestCompletion.query.filter_by(
        side_quest_id=side_quest.id, quest_id=quest_id
    ).order_by(SideQuestCompletion.completed_at.desc()).all()

    total = len(completions)
    last_completed = completions[0].completed_at if completions else None
    now = datetime.now(timezone.utc)

    if last_completed and last_completed.tzinfo is None:
        last_completed = last_completed.replace(tzinfo=timezone.utc)

    if side_quest.repeat_type == "one_time":
        return {
            "can_complete": total == 0,
            "last_completed": last_completed,
            "cooldown_until": None,
            "total_completions": total,
        }

    elif side_quest.repeat_type == "repeatable":
        return {
            "can_complete": True,
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
