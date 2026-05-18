"""Ledger Engine: Records transactions and calculates currency balances."""
from app import db
from app.models import Transaction, Quest


def get_balance(quest_id):
    """Calculate current spendable balance for a quest."""
    earned = db.session.query(db.func.coalesce(db.func.sum(Transaction.amount), 0)).filter(
        Transaction.quest_id == quest_id,
        Transaction.type.in_(["earn", "side_quest_reward", "adjustment"]),
    ).scalar()

    spent = db.session.query(db.func.coalesce(db.func.sum(Transaction.amount), 0)).filter(
        Transaction.quest_id == quest_id,
        Transaction.type == "spend",
    ).scalar()

    return earned - spent


def get_lifetime_earned(quest_id):
    """Total currency ever earned (never decreases). Used for prize tier unlocks."""
    return db.session.query(db.func.coalesce(db.func.sum(Transaction.amount), 0)).filter(
        Transaction.quest_id == quest_id,
        Transaction.type.in_(["earn", "side_quest_reward"]),
    ).scalar()


def get_journey_totals(journey_id):
    """Get earned totals per quest for a journey (for Co-Op goal checking)."""
    results = db.session.query(
        Quest.id,
        Quest.member_id,
        db.func.coalesce(db.func.sum(Transaction.amount), 0).label("total_earned"),
    ).join(Transaction, Transaction.quest_id == Quest.id).filter(
        Quest.journey_id == journey_id,
        Transaction.type.in_(["earn", "side_quest_reward"]),
    ).group_by(Quest.id, Quest.member_id).all()

    return {r.member_id: r.total_earned for r in results}


def record_earn(quest_id, amount, description, activity_log_id=None, earning_rule_id=None):
    """Record a currency earn transaction."""
    txn = Transaction(
        quest_id=quest_id,
        type="earn",
        amount=amount,
        description=description,
        activity_log_id=activity_log_id,
        earning_rule_id=earning_rule_id,
    )
    db.session.add(txn)
    return txn


def record_spend(quest_id, amount, description):
    """Record a currency spend transaction. Returns None if insufficient balance."""
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
    txn = Transaction(
        quest_id=quest_id,
        type="side_quest_reward",
        amount=amount,
        description=description,
    )
    db.session.add(txn)
    return txn
