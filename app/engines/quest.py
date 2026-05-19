"""Quest Engine: Theme/label resolution and earning rule calculation."""
from app import db
from app.models import (
    Quest, ActivityType, EarningRule, ActivityLog, Transaction,
)
from app.engines.ledger import record_earn


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

    return log, transactions


def _apply_earning_rules(quest, activity_type, activity_log):
    """Apply earning rules for an activity log entry."""
    rules = EarningRule.query.filter_by(activity_type_id=activity_type.id).all()
    transactions = []

    for rule in rules:
        earned = _calculate_reward(rule, activity_log)
        if earned > 0:
            txn = record_earn(
                quest_id=quest.id,
                amount=earned,
                description=f"{activity_log.quantity} {activity_type.unit_label} logged",
                activity_log_id=activity_log.id,
                earning_rule_id=rule.id,
            )
            transactions.append(txn)

    return transactions


def _calculate_reward(rule, activity_log):
    """
    Calculate currency reward based on rule type and logged quantity.

    per_batch: for every quantity_required units, award currency_reward.
               e.g., 120 pages with rule (50 pages → 10 currency) = 20 currency
               Remainder carries forward implicitly via cumulative calculation.

    per_log: if the logged quantity >= quantity_required, award currency_reward once.
             e.g., log any books >= 1 → earn 25 currency.
    """
    if rule.rule_type == "per_batch":
        return (activity_log.quantity // rule.quantity_required) * rule.currency_reward

    elif rule.rule_type == "per_log":
        if activity_log.quantity >= rule.quantity_required:
            return rule.currency_reward

    return 0
