"""Lifetime Stats Engine: Aggregates activity data across all journeys for a member."""
from app import db
from app.models import ActivityLog, Quest, Transaction, Journey, SideQuestCompletion


def get_total_logs(member_id):
    """Total number of activity log entries across all journeys."""
    return db.session.query(db.func.count(ActivityLog.id)).join(
        Quest, ActivityLog.quest_id == Quest.id
    ).filter(Quest.member_id == member_id).scalar()


def get_total_currency_earned(member_id):
    """Total currency earned across all journeys (lifetime)."""
    return db.session.query(
        db.func.coalesce(db.func.sum(Transaction.amount), 0)
    ).join(Quest, Transaction.quest_id == Quest.id).filter(
        Quest.member_id == member_id,
        Transaction.type.in_(["earn", "side_quest_reward"]),
    ).scalar()


def get_journeys_completed(member_id):
    """Number of journeys the member has been part of that are completed."""
    return db.session.query(db.func.count(db.distinct(Journey.id))).join(
        Quest, Quest.journey_id == Journey.id
    ).filter(
        Quest.member_id == member_id,
        Journey.status == "completed",
    ).scalar()


def get_stats_by_activity_type(member_id):
    """Get total quantity logged per activity type name across all journeys."""
    from app.models import ActivityType

    results = db.session.query(
        ActivityType.name,
        ActivityType.unit_label,
        db.func.sum(ActivityLog.quantity).label("total_quantity"),
        db.func.count(ActivityLog.id).label("log_count"),
    ).join(ActivityType, ActivityLog.activity_type_id == ActivityType.id).join(
        Quest, ActivityLog.quest_id == Quest.id
    ).filter(
        Quest.member_id == member_id,
    ).group_by(ActivityType.name, ActivityType.unit_label).all()

    return [
        {"name": r.name, "unit": r.unit_label, "total": r.total_quantity, "logs": r.log_count}
        for r in results
    ]


def get_side_quests_completed(member_id):
    """Total side quests completed across all journeys."""
    return db.session.query(db.func.count(SideQuestCompletion.id)).join(
        Quest, SideQuestCompletion.quest_id == Quest.id
    ).filter(Quest.member_id == member_id).scalar()


def get_all_stats(member_id):
    """Get a complete lifetime stats summary for a member."""
    return {
        "total_logs": get_total_logs(member_id),
        "total_currency_earned": get_total_currency_earned(member_id),
        "journeys_completed": get_journeys_completed(member_id),
        "side_quests_completed": get_side_quests_completed(member_id),
        "by_activity_type": get_stats_by_activity_type(member_id),
    }
