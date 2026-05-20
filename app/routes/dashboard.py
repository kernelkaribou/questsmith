import math

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify

from app import db
from app.models import (
    Member, Campaign, Quest, PartyGoal, QuestLevel, QuestLevelUnlock, ShopItem,
    ShopPurchase, AchievementUnlock, Achievement, ActivityLog, ActivityType,
)
from app.engines import ledger, validation, side_quest as side_quest_engine, quest as quest_engine, lifetime

bp = Blueprint("dashboard", __name__, url_prefix="/")


@bp.route("/")
def index():
    """Landing page — show active campaigns (campaigns)."""
    session.pop("active_member_id", None)
    session.pop("active_member_name", None)
    campaigns = Campaign.query.filter_by(status="active").all()
    # Also find solo quests (not in any campaign)
    solo_quests = Quest.query.filter_by(campaign_id=None, status="active").filter(Quest.completed_at.is_(None)).all()
    return render_template("dashboard/index.html", campaigns=campaigns, solo_quests=solo_quests)


@bp.route("/quest/<int:quest_id>")
def quest_view(quest_id):
    """Main quest dashboard."""
    quest = db.session.get(Quest, quest_id)
    campaign = quest.campaign
    member = quest.member
    is_admin = session.get("admin", False)

    balance = ledger.get_balance(quest_id)
    total_earned = ledger.get_lifetime_earned(quest_id)

    # Party Goals progress (only if quest is in a campaign)
    goal_progress = []
    if campaign:
        party_goals = PartyGoal.query.filter_by(campaign_id=campaign.id).order_by(PartyGoal.sort_order).all()
        campaign_totals = ledger.get_campaign_totals(campaign.id)
        combined_total = sum(campaign_totals.values())
        my_contribution = campaign_totals.get(member.id, 0)
        num_members = db.session.query(Quest.member_id).filter_by(campaign_id=campaign.id).distinct().count()
        for goal in party_goals:
            target = goal.target_amount or 1
            min_req = math.ceil(target / num_members) if num_members > 0 else target
            all_met_min = all(
                campaign_totals.get(mid, 0) >= min_req
                for mid, in db.session.query(Quest.member_id).filter_by(campaign_id=campaign.id).distinct()
            )
            goal_progress.append({
                "goal": goal,
                "current": combined_total,
                "my_contribution": my_contribution,
                "my_percent": min(100, int(my_contribution / target * 100)),
                "percent": min(100, int(combined_total / target * 100)),
                "my_remaining": max(0, min_req - my_contribution),
                "min_required": min_req,
                "min_marker_percent": min(100, int(min_req / target * 100)) if min_req else 0,
                "all_met_min": all_met_min,
            })

    # Quest Levels (belong to quest now)
    levels = QuestLevel.query.filter_by(quest_id=quest_id).order_by(QuestLevel.threshold).all()
    unlocked_levels = validation.get_unlocked_levels(quest_id)

    # Check for new level unlocks (only relevant if admin just logged)
    from app.engines.validation import check_level_unlocks
    new_level_unlocks = check_level_unlocks(quest_id)
    if new_level_unlocks:
        db.session.commit()

    # Combined Shop: quest-owned + campaign-owned
    shop_items = ShopItem.query.filter_by(quest_id=quest_id).order_by(ShopItem.sort_order).all()
    if campaign:
        campaign_shop = ShopItem.query.filter_by(campaign_id=campaign.id).order_by(ShopItem.sort_order).all()
        shop_items = shop_items + campaign_shop

    # Side quests (belong to quest now) - split into available and completed
    sq_data = side_quest_engine.get_available_side_quests(quest_id)
    sq_available = [{"quest": item["side_quest"], "available": item["can_complete"]} for item in sq_data if item["can_complete"]]
    sq_completed = [{"quest": item["side_quest"], "available": item["can_complete"]} for item in sq_data if not item["can_complete"]]

    # Quest chains
    chain_data = side_quest_engine.get_available_chains(quest_id)

    # Achievements for this member
    unlocks = AchievementUnlock.query.filter_by(member_id=member.id).all()
    achievements = [db.session.get(Achievement, u.achievement_id) for u in unlocks]

    # Activity timeline (recent 5; full log accessible via View Full History)
    recent_logs = ActivityLog.query.filter_by(quest_id=quest_id).order_by(ActivityLog.logged_at.desc()).limit(5).all()

    # Shop purchase history
    purchases = ShopPurchase.query.filter_by(quest_id=quest_id).order_by(ShopPurchase.purchased_at.desc()).all()

    # Explicit activity type list for dropdown (issue: dynamic lazy can confuse templates)
    activity_types = ActivityType.query.filter_by(quest_id=quest_id).order_by(ActivityType.sort_order).all()

    # Earning progress (units toward next currency)
    earning_progress = quest_engine.get_earning_progress(quest_id)

    # Theme context
    ctx = quest_engine.get_quest_context(quest_id)

    return render_template(
        "dashboard/quest.html",
        quest=quest,
        campaign=campaign,
        member=member,
        balance=balance,
        total_earned=total_earned,
        goal_progress=goal_progress,
        levels=levels,
        unlocked_levels=unlocked_levels,
        shop_items=shop_items,
        sq_available=sq_available,
        sq_completed=sq_completed,
        chain_data=chain_data,
        earning_progress=earning_progress,
        achievements=achievements,
        recent_logs=recent_logs,
        purchases=purchases,
        activity_types=activity_types,
        ctx=ctx,
        is_admin=is_admin,
    )


@bp.route("/member/<int:member_id>")
def member_select(member_id):
    """Show active quests for a member to pick."""
    member = db.session.get(Member, member_id)
    session["active_member_id"] = member.id
    session["active_member_name"] = member.name
    quests = Quest.query.filter_by(member_id=member_id, status="active").filter(Quest.completed_at.is_(None)).all()
    completed_quests = Quest.query.filter_by(member_id=member_id, status="active").filter(Quest.completed_at.isnot(None)).all()
    if not completed_quests and len(quests) == 1:
        return redirect(url_for("dashboard.quest_view", quest_id=quests[0].id))
    return render_template("dashboard/member_select.html", member=member, quests=quests, completed_quests=completed_quests)


@bp.route("/member/<int:member_id>/profile")
def member_profile(member_id):
    """Lifetime stats and achievement showcase for a member."""
    member = db.session.get(Member, member_id)
    stats = lifetime.get_all_stats(member_id)

    unlocks = AchievementUnlock.query.filter_by(member_id=member_id).order_by(AchievementUnlock.unlocked_at.desc()).all()
    achievements = []
    for u in unlocks:
        ach = db.session.get(Achievement, u.achievement_id)
        achievements.append({"achievement": ach, "unlocked_at": u.unlocked_at})

    all_quests = Quest.query.filter_by(member_id=member_id).order_by(Quest.created_at.desc()).all()

    return render_template(
        "dashboard/profile.html",
        member=member,
        stats=stats,
        achievements=achievements,
        all_quests=all_quests,
    )


@bp.route("/quest/<int:quest_id>/history")
def quest_history(quest_id):
    """Activity log timeline for a specific quest."""
    quest = db.session.get(Quest, quest_id)
    logs = ActivityLog.query.filter_by(quest_id=quest_id).order_by(ActivityLog.logged_at.desc()).all()
    ctx = quest_engine.get_quest_context(quest_id)
    return render_template(
        "dashboard/history.html",
        quest=quest,
        logs=logs,
        ctx=ctx,
    )


@bp.route("/campaign/<int:campaign_id>")
def campaign_view(campaign_id):
    """Campaign overview scorecard — game-show style party display."""
    campaign = db.session.get(Campaign, campaign_id)
    quests = Quest.query.filter_by(campaign_id=campaign_id, status="active").all()
    campaign_totals = ledger.get_campaign_totals(campaign_id)
    combined_total = sum(campaign_totals.values())

    # Build adventurer data
    adventurers = []
    for q in quests:
        member = q.member
        contribution = campaign_totals.get(member.id, 0)
        levels = QuestLevel.query.filter_by(quest_id=q.id).order_by(QuestLevel.threshold).all()
        current_level = "Level 0"
        for lv in levels:
            earned = ledger.get_lifetime_earned(q.id)
            if earned >= lv.threshold:
                current_level = lv.name
        adventurers.append({
            "member": member,
            "quest": q,
            "contribution": contribution,
            "current_level": current_level,
        })

    # Party goals (sorted by target value ascending)
    party_goals = PartyGoal.query.filter_by(campaign_id=campaign_id).order_by(PartyGoal.target_amount.asc()).all()
    num_members = len(quests) if quests else 1
    goals_data = []
    for goal in party_goals:
        target = goal.target_amount or 1
        min_req = math.ceil(target / num_members) if num_members > 0 else target
        all_met_min = all(
            campaign_totals.get(q.member_id, 0) >= min_req for q in quests
        )
        # Per-member contribution toward their minimum
        member_progress = []
        capped_total = 0
        for q in quests:
            contrib = campaign_totals.get(q.member_id, 0)
            capped = min(contrib, min_req)
            capped_total += capped
            member_progress.append({
                "member": q.member,
                "contribution": contrib,
                "percent": min(100, int(contrib / min_req * 100)) if min_req > 0 else 100,
                "met_min": contrib >= min_req,
            })
        pct = min(100, int(capped_total / target * 100))
        is_complete = capped_total >= target and all_met_min
        goals_data.append({
            "goal": goal,
            "current": capped_total,
            "percent": pct,
            "complete": is_complete,
            "min_required": min_req,
            "member_progress": member_progress,
        })

    # Mark the first incomplete goal as "active"; hide progress on future goals
    active_found = False
    for g in goals_data:
        if g["complete"]:
            g["show_progress"] = True
        elif not active_found:
            g["show_progress"] = True
            g["active"] = True
            active_found = True
        else:
            g["show_progress"] = False

    return render_template(
        "dashboard/campaign.html",
        campaign=campaign,
        adventurers=adventurers,
        goals=goals_data,
        combined_total=combined_total,
    )


@bp.route("/quest/<int:quest_id>/redeem", methods=["POST"])
def redeem(quest_id):
    """Self-service shop redemption (no admin required)."""
    item_id = int(request.form["item_id"])
    item = db.session.get(ShopItem, item_id)
    quest = db.session.get(Quest, quest_id)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if not item or not quest:
        msg = "Invalid item or quest"
        if is_ajax:
            return jsonify(success=False, message=msg), 400
        flash(msg, "error")
        return redirect(url_for("dashboard.index"))

    # Validate item belongs to this quest or its campaign
    if item.quest_id != quest_id and not (quest.campaign_id and item.campaign_id == quest.campaign_id):
        msg = "Item not available for this quest"
        if is_ajax:
            return jsonify(success=False, message=msg), 403
        flash(msg, "error")
        return redirect(url_for("dashboard.quest_view", quest_id=quest_id))

    if item.cost == 0:
        purchase = ShopPurchase(shop_item_id=item.id, quest_id=quest_id, transaction_id=None)
        db.session.add(purchase)
        db.session.commit()
        msg = f"Redeemed '{item.name}'!"
        if is_ajax:
            return jsonify(success=True, message=msg)
        flash(msg, "success")
    else:
        txn = ledger.record_spend(quest_id, item.cost, f"Purchased: {item.name}")
        if txn:
            db.session.flush()
            purchase = ShopPurchase(shop_item_id=item.id, quest_id=quest_id, transaction_id=txn.id)
            db.session.add(purchase)
            db.session.commit()
            msg = f"Redeemed '{item.name}'!"
            if is_ajax:
                return jsonify(success=True, message=msg)
            flash(msg, "success")
        else:
            msg = f"Not enough {quest.display_currency} for '{item.name}'"
            if is_ajax:
                return jsonify(success=False, message=msg), 400
            flash(msg, "error")

    return redirect(url_for("dashboard.quest_view", quest_id=quest_id))
