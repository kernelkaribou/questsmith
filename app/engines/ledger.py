"""Ledger Engine: Records transactions and calculates currency balances."""
from app import db
from app.models import Transaction, Quest


def get_balance(quest_id):
    """Calculate current spendable balance for a quest."""
    earned = db.session.query(db.func.coalesce(db.func.sum(Transaction.amount), 0)).filter(
        Transaction.quest_id == quest_id,
        Transaction.type.in_(["earn", "side_quest_reward", "completion_bonus", "adjustment", "refund"]),
    ).scalar()

    spent = db.session.query(db.func.coalesce(db.func.sum(Transaction.amount), 0)).filter(
        Transaction.quest_id == quest_id,
        Transaction.type == "spend",
    ).scalar()

    reversed = db.session.query(db.func.coalesce(db.func.sum(Transaction.amount), 0)).filter(
        Transaction.quest_id == quest_id,
        Transaction.type == "reversal",
    ).scalar()

    return earned - spent - reversed


def get_lifetime_earned(quest_id):
    """Total currency ever earned (minus reversals). Used for prize tier unlocks."""
    earned = db.session.query(db.func.coalesce(db.func.sum(Transaction.amount), 0)).filter(
        Transaction.quest_id == quest_id,
        Transaction.type.in_(["earn", "side_quest_reward", "completion_bonus"]),
    ).scalar()

    reversed = db.session.query(db.func.coalesce(db.func.sum(Transaction.amount), 0)).filter(
        Transaction.quest_id == quest_id,
        Transaction.type == "reversal",
    ).scalar()

    return max(0, earned - reversed)


def get_journey_totals(journey_id):
    """Get earned totals per quest for a journey (for Co-Op goal checking)."""
    earned_results = db.session.query(
        Quest.id,
        Quest.member_id,
        db.func.coalesce(db.func.sum(Transaction.amount), 0).label("total_earned"),
    ).join(Transaction, Transaction.quest_id == Quest.id).filter(
        Quest.journey_id == journey_id,
        Transaction.type.in_(["earn", "side_quest_reward"]),
    ).group_by(Quest.id, Quest.member_id).all()

    reversed_results = db.session.query(
        Quest.id,
        Quest.member_id,
        db.func.coalesce(db.func.sum(Transaction.amount), 0).label("total_reversed"),
    ).join(Transaction, Transaction.quest_id == Quest.id).filter(
        Quest.journey_id == journey_id,
        Transaction.type == "reversal",
    ).group_by(Quest.id, Quest.member_id).all()

    reversed_map = {r.member_id: r.total_reversed for r in reversed_results}
    return {r.member_id: max(0, r.total_earned - reversed_map.get(r.member_id, 0)) for r in earned_results}


def record_earn(quest_id, amount, description, activity_log_id=None, earning_rule_id=None, batches_awarded=None):
    """Record a currency earn transaction."""
    if amount <= 0:
        raise ValueError(f"Earn amount must be positive, got {amount}")

    txn = Transaction(
        quest_id=quest_id,
        type="earn",
        amount=amount,
        description=description,
        activity_log_id=activity_log_id,
        earning_rule_id=earning_rule_id,
        batches_awarded=batches_awarded,
    )
    db.session.add(txn)
    return txn


def record_spend(quest_id, amount, description):
    """Record a currency spend transaction. Returns None if insufficient balance."""
    if amount <= 0:
        raise ValueError(f"Spend amount must be positive, got {amount}")

    balance = get_balance(quest_id)
    if balance < amount:
        return None

    txn = Transaction(
        quest_id=quest_id,
        type="spend",
        amount=amount,
        description=description,
    )
    db.session.add(txn)
    return txn


def record_side_quest_reward(quest_id, amount, description):
    """Record currency earned from a side quest."""
    if amount <= 0:
        raise ValueError(f"Side quest reward amount must be positive, got {amount}")

    txn = Transaction(
        quest_id=quest_id,
        type="side_quest_reward",
        amount=amount,
        description=description,
    )
    db.session.add(txn)
    return txn


def record_completion_bonus(quest_id, amount, description):
    """Record currency earned from completing a quest."""
    if amount <= 0:
        raise ValueError(f"Completion bonus must be positive, got {amount}")

    txn = Transaction(
        quest_id=quest_id,
        type="completion_bonus",
        amount=amount,
        description=description,
    )
    db.session.add(txn)
    return txn
