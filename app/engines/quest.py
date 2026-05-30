"""Quest Engine: Theme/label resolution and earning rule calculation."""
from datetime import datetime, timezone

from app import db
from app.models import (
    Quest, ActivityType, EarningRule, ActivityLog, Transaction,
)
from app.engines.ledger import record_earn, record_completion_bonus, record_reversal, get_lifetime_earned


def get_quest_context(quest_id):
    """Get full themed context for rendering a quest's UI."""
    quest = db.session.get(Quest, quest_id)
    if not quest:
        return None

    return {
        "quest": quest,
        "theme_name": quest.theme_name,
        "graphic_url": quest.theme_graphic_url,
        "colors": {"primary": quest.color_primary, "secondary": quest.color_secondary},
        "currency_label": quest.display_currency,
        "progress_label": quest.display_progress,
        "party_goal_label": quest.display_party_goal,
    }


def log_activity(quest_id, activity_type_id, quantity, description=None, notes=None):
    """
    Log an activity and apply earning rules to generate transactions.
    Returns the activity log entry and any transactions created.
    """
    quest = db.session.get(Quest, quest_id)
    activity_type = db.session.get(ActivityType, activity_type_id)

    if not quest or not activity_type:
        return None, []
    if activity_type.quest_id != quest_id:
        return None, []
    if quantity <= 0:
        return None, []

    # Create activity log
    log = ActivityLog(
        quest_id=quest_id,
        activity_type_id=activity_type_id,
        quantity=quantity,
        description=description,
        notes=notes,
    )
    db.session.add(log)
    db.session.flush()

    # Apply earning rules
    transactions = _apply_earning_rules(quest, activity_type, log)

    # Check quest completion
    completion_txn = _check_quest_completion(quest)
    if completion_txn:
        transactions.append(completion_txn)

    # Check level unlocks
    from app.engines.validation import check_level_unlocks
    check_level_unlocks(quest_id)

    return log, transactions


def _apply_earning_rules(quest, activity_type, activity_log):
    """Apply earning rules for an activity log entry."""
    rules = EarningRule.query.filter_by(activity_type_id=activity_type.id).all()
    transactions = []

    for rule in rules:
        earned, batches = _calculate_reward(rule, quest.id, activity_type.id, activity_log)
        if earned > 0:
            txn = record_earn(
                quest_id=quest.id,
                amount=earned,
                description=f"{activity_log.quantity} {activity_type.unit_label} logged",
                activity_log_id=activity_log.id,
                earning_rule_id=rule.id,
                batches_awarded=batches,
            )
            transactions.append(txn)

    return transactions


def _calculate_reward(rule, quest_id, activity_type_id, activity_log):
    """
    Calculate currency reward based on rule type.
    Returns (amount_earned, batches_awarded).

    per_batch: Uses cumulative total across all logs for this activity type.
              Compares total batches possible vs already paid to find new earnings.

    per_log: If the logged quantity >= quantity_required, award currency_reward once.
    """
    if rule.rule_type == "per_batch":
        # Sum all logged quantity for this activity type on this quest (exclude reversed)
        total_logged = db.session.query(
            db.func.coalesce(db.func.sum(ActivityLog.quantity), 0)
        ).filter(
            ActivityLog.quest_id == quest_id,
            ActivityLog.activity_type_id == activity_type_id,
            ActivityLog.reversed == False,
        ).scalar()

        # Count batches already awarded (exclude reversed activity logs)
        batches_already_paid = db.session.query(
            db.func.coalesce(db.func.sum(Transaction.batches_awarded), 0)
        ).join(ActivityLog, Transaction.activity_log_id == ActivityLog.id).filter(
            Transaction.quest_id == quest_id,
            Transaction.earning_rule_id == rule.id,
            Transaction.type == "earn",
            ActivityLog.reversed == False,
        ).scalar()

        total_batches_ever = total_logged // rule.quantity_required
        new_batches = total_batches_ever - batches_already_paid

        if new_batches > 0:
            return new_batches * rule.currency_reward, new_batches
        return 0, 0

    elif rule.rule_type == "per_log":
        if activity_log.quantity >= rule.quantity_required:
            return rule.currency_reward, None

    return 0, None


def _reconcile_batch_overpayment(quest_id, activity_type_id):
    """
    After a reversal, check if per_batch rules have been overpaid.
    If total valid batches < batches already paid, create reversal transactions.
    """
    from app.engines.ledger import record_reversal

    rules = EarningRule.query.filter_by(activity_type_id=activity_type_id, rule_type="per_batch").all()

    for rule in rules:
        # Current valid quantity (excluding reversed logs)
        total_logged = db.session.query(
            db.func.coalesce(db.func.sum(ActivityLog.quantity), 0)
        ).filter(
            ActivityLog.quest_id == quest_id,
            ActivityLog.activity_type_id == activity_type_id,
            ActivityLog.reversed == False,
        ).scalar()

        valid_batches = total_logged // rule.quantity_required

        # Total batches paid (only from non-reversed logs)
        batches_paid = db.session.query(
            db.func.coalesce(db.func.sum(Transaction.batches_awarded), 0)
        ).join(ActivityLog, Transaction.activity_log_id == ActivityLog.id).filter(
            Transaction.quest_id == quest_id,
            Transaction.earning_rule_id == rule.id,
            Transaction.type == "earn",
            ActivityLog.reversed == False,
        ).scalar()

        overpaid_batches = batches_paid - valid_batches
        if overpaid_batches > 0:
            overpaid_amount = overpaid_batches * rule.currency_reward
            record_reversal(
                quest_id, overpaid_amount,
                f"Reconciliation: {overpaid_batches} batch(es) no longer valid",
            )


def _check_quest_completion(quest):
    """Check if quest has reached its completion target and award bonus."""
    if quest.completion_target is None or quest.completed_at:
        return None

    lifetime = get_lifetime_earned(quest.id)
    if lifetime >= quest.completion_target:
        quest.completed_at = datetime.now(timezone.utc)
        db.session.add(quest)

        if quest.completion_bonus and quest.completion_bonus > 0:
            return record_completion_bonus(
                quest.id, quest.completion_bonus,
                "Quest Complete! Victory bonus!",
            )
    return None


def get_earning_progress(quest_id):
    """
    Get progress toward next currency for each per_batch earning rule.
    Returns list of dicts with rule info, cumulative progress, and remainder.
    """
    from app.models import ActivityType
    quest = db.session.get(Quest, quest_id)
    if not quest:
        return []

    activity_types = ActivityType.query.filter_by(quest_id=quest_id).all()
    progress = []

    for at in activity_types:
        if at.is_milestone:
            # Completions are flat per-log rewards, not cumulative — never show
            # a progress bar even if a legacy rule is still marked per_batch.
            continue
        rules = EarningRule.query.filter_by(activity_type_id=at.id, rule_type="per_batch").all()
        total_logged = db.session.query(
            db.func.coalesce(db.func.sum(ActivityLog.quantity), 0)
        ).filter(
            ActivityLog.quest_id == quest_id,
            ActivityLog.activity_type_id == at.id,
            ActivityLog.reversed == False,
        ).scalar()

        for rule in rules:
            remainder = total_logged % rule.quantity_required
            units_to_next = rule.quantity_required - remainder
            progress.append({
               "activity_type": at,
               "rule": rule,
               "total_logged": total_logged,
               "remainder": remainder,
               "units_to_next": units_to_next,
               "percent": int(remainder / rule.quantity_required * 100) if rule.quantity_required else 0,
            })

    return progress


def get_completion_stats(quest_id):
    """
    Backward-looking completion tallies for a quest's dashboard.

    Returns (activity_stats, quest_stats):
      - activity_stats: for each completion (milestone) activity type, the count
        of non-reversed activity logs -> [{"name", "count"}].
      - quest_stats: a single merged "Quest Completions" entry counting each
        non-reversed standalone side quest completion plus each completed chain,
        or [] when the quest has no standalone side quests or chains.

    All counts are reversal-aware: reversed activity logs are excluded, side
    quest completions with reversed_at set are excluded, and chains are counted
    only while completed_at is populated (cleared when a completing step is
    reversed).
    """
    from app.models import SideQuest, SideQuestChain, SideQuestCompletion

    activity_stats = []
    milestone_types = ActivityType.query.filter_by(
        quest_id=quest_id, is_milestone=True
    ).order_by(ActivityType.sort_order).all()
    for at in milestone_types:
        count = ActivityLog.query.filter_by(
            quest_id=quest_id, activity_type_id=at.id, reversed=False
        ).count()
        activity_stats.append({"name": at.name, "count": count})

    quest_stats = []
    has_standalone_sq = SideQuest.query.filter(
        SideQuest.quest_id == quest_id, SideQuest.chain_id.is_(None)
    ).count() > 0
    has_chains = SideQuestChain.query.filter_by(quest_id=quest_id).count() > 0
    if has_standalone_sq or has_chains:
        sq_done = SideQuestCompletion.query.join(SideQuestCompletion.side_quest).filter(
            SideQuestCompletion.quest_id == quest_id,
            SideQuestCompletion.reversed_at.is_(None),
            SideQuest.chain_id.is_(None),
        ).count()
        chain_done = SideQuestChain.query.filter(
            SideQuestChain.quest_id == quest_id,
            SideQuestChain.completed_at.isnot(None),
        ).count()
        quest_stats.append({"name": "Quest Completions", "count": sq_done + chain_done})

    return activity_stats, quest_stats