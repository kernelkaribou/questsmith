"""Achievement Engine: Evaluate auto-trigger conditions and manage unlocks."""
from datetime import datetime, timezone

from app import db
from app.models import Achievement, AchievementUnlock
from app.engines.lifetime import get_all_stats


def check_achievements(member_id):
    """
    Evaluate all auto-triggered achievements for a member.
    Unlocks any newly qualified achievements. Returns list of new unlocks.
    """
    stats = get_all_stats(member_id)
    auto_achievements = Achievement.query.filter_by(trigger_type="auto").all()

    already_unlocked = set(
        row.achievement_id for row in
        AchievementUnlock.query.filter_by(member_id=member_id).all()
    )

    new_unlocks = []
    for achievement in auto_achievements:
        if achievement.id in already_unlocked:
            continue

        if _evaluate_condition(achievement.trigger_condition, stats):
            unlock = AchievementUnlock(
                achievement_id=achievement.id,
                member_id=member_id,
            )
            db.session.add(unlock)
            new_unlocks.append(achievement)

    return new_unlocks


def manually_award(achievement_id, member_id):
    """Manually award an achievement to a member. Returns None if already unlocked."""
    existing = AchievementUnlock.query.filter_by(
        achievement_id=achievement_id, member_id=member_id
    ).first()

    if existing:
        return None

    unlock = AchievementUnlock(
        achievement_id=achievement_id,
        member_id=member_id,
    )
    db.session.add(unlock)
    return unlock


def get_member_achievements(member_id):
    """Get all achievements with unlock status for a member."""
    all_achievements = Achievement.query.all()
    unlocked = {
        row.achievement_id: row.unlocked_at
        for row in AchievementUnlock.query.filter_by(member_id=member_id).all()
    }

    return [
        {
            "achievement": a,
            "unlocked": a.id in unlocked,
            "unlocked_at": unlocked.get(a.id),
        }
        for a in all_achievements
    ]


def _evaluate_condition(condition, stats):
    """Evaluate a trigger condition against lifetime stats."""
    if not condition:
        return False

    metric = condition.get("metric")
    threshold = condition.get("threshold", 0)

    if metric == "total_logs":
        return stats["total_logs"] >= threshold

    elif metric == "total_currency_earned":
        return stats["total_currency_earned"] >= threshold

    elif metric == "campaigns_completed":
        return stats["campaigns_completed"] >= threshold

    elif metric == "side_quests_completed":
        return stats["side_quests_completed"] >= threshold

    return False
