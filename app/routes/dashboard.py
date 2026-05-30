import math

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, abort

from app import db
from app.models import (
    Member, MemberAvatar, Campaign, Quest, PartyGoal, QuestLevel, QuestLevelUnlock, ShopItem,
    ShopPurchase, AchievementUnlock, Achievement, ActivityLog, ActivityType, Transaction,
    SideQuestCompletion, SideQuestChain,
)
from app.engines import ledger, validation, side_quest as side_quest_engine, quest as quest_engine, lifetime
from app.engines import party_goals as party_goals_engine, shop as shop_engine

bp = Blueprint("dashboard", __name__, url_prefix="/")


def _get_or_404(model, id):
    obj = db.session.get(model, id)
    if obj is None:
        abort(404)
    return obj


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
    quest = _get_or_404(Quest, quest_id)
    campaign = quest.campaign
    member = quest.member
    is_admin = session.get("admin", False)

    balance = ledger.get_balance(quest_id)
    total_earned = ledger.get_lifetime_earned(quest_id)

    # Party Goals progress (only if quest is in a campaign)
    goal_progress = []
    if campaign:
        goal_progress = party_goals_engine.get_member_goal_progress(campaign.id, member.id)

    # Quest Levels (belong to quest now)
    levels = QuestLevel.query.filter_by(quest_id=quest_id).order_by(QuestLevel.threshold).all()
    unlocked_levels = validation.get_unlocked_levels(quest_id)

    # Check for new level unlocks (only relevant if admin just logged)
    from app.engines.validation import check_level_unlocks
    new_level_unlocks = check_level_unlocks(quest_id)
    if new_level_unlocks:
        db.session.commit()

    # Combined Shop: quest-owned + campaign-owned
    shop_items = ShopItem.query.filter_by(quest_id=quest_id).order_by(ShopItem.cost).all()
    if campaign:
        campaign_shop = ShopItem.query.filter_by(campaign_id=campaign.id).order_by(ShopItem.cost).all()
        shop_items = shop_items + campaign_shop
        shop_items.sort(key=lambda x: x.cost)

    # Side quests (belong to quest now) - split into available and completed
    sq_data = side_quest_engine.get_available_side_quests(quest_id)
    sq_available = [{"quest": item["side_quest"], "available": item["can_complete"]} for item in sq_data if item["can_complete"]]
    sq_completed = [{"quest": item["side_quest"], "available": item["can_complete"]} for item in sq_data if not item["can_complete"]]

    # Quest chains (active + completed)
    chain_data = side_quest_engine.get_available_chains(quest_id)
    chains_completed = side_quest_engine.get_completed_chains(quest_id)

    # Achievements for this member
    unlocks = AchievementUnlock.query.filter_by(member_id=member.id).all()
    achievements = [db.session.get(Achievement, u.achievement_id) for u in unlocks]

    # Activity timeline (fetch more for an accurate merged journal; capped after merge)
    recent_logs = ActivityLog.query.filter_by(quest_id=quest_id, reversed=False).order_by(ActivityLog.logged_at.desc()).limit(15).all()
    activity_count = ActivityLog.query.filter_by(quest_id=quest_id, reversed=False).count()

    # Side quest / chain completions for the journal
    # Standalone completions (not chain steps) + chain completions (as single entries)
    standalone_completions = SideQuestCompletion.query.filter_by(quest_id=quest_id).join(
        SideQuestCompletion.side_quest
    ).filter(
        SideQuestCompletion.reversed_at.is_(None),
        db.text("side_quests.chain_id IS NULL"),
    ).order_by(SideQuestCompletion.completed_at.desc()).limit(10).all()

    completed_chain_entries = SideQuestChain.query.filter_by(quest_id=quest_id).filter(
        SideQuestChain.completed_at.isnot(None)
    ).order_by(SideQuestChain.completed_at.desc()).limit(10).all()

    # Merge into a unified list sorted by date
    journal_completions = []
    for c in standalone_completions:
        journal_completions.append({"type": "side_quest", "name": c.side_quest.name, "reward": c.side_quest.currency_reward, "prize": c.side_quest.prize_description, "date": c.completed_at})
    for chain in completed_chain_entries:
        journal_completions.append({"type": "chain", "name": chain.name, "reward": chain.currency_reward, "prize": chain.prize_description, "date": chain.completed_at})
    journal_completions.sort(key=lambda x: x["date"], reverse=True)

    # Shop purchase history
    purchases = ShopPurchase.query.filter_by(quest_id=quest_id).order_by(ShopPurchase.purchased_at.desc()).all()

    # Bonus awards (adjustments)
    bonuses = Transaction.query.filter_by(quest_id=quest_id, type="adjustment").order_by(Transaction.created_at.desc()).all()

    # Unified journal: merge all event types into a single descending timeline
    journal = []
    for log in recent_logs:
        journal.append({"kind": "activity", "date": log.logged_at, "log": log})
    for jc in journal_completions:
        journal.append({"kind": "completion", "date": jc["date"], "jc": jc})
    for p in purchases:
        journal.append({"kind": "purchase", "date": p.purchased_at, "p": p})
    for b in bonuses:
        journal.append({"kind": "bonus", "date": b.created_at, "b": b})
    journal.sort(key=lambda x: x["date"], reverse=True)
    journal = journal[:8]

    # Explicit activity type list for dropdown (issue: dynamic lazy can confuse templates)
    activity_types = ActivityType.query.filter_by(quest_id=quest_id).order_by(ActivityType.sort_order).all()

    # Earning progress (units toward next currency)
    earning_progress = quest_engine.get_earning_progress(quest_id)

    # Completion (milestone) tally — infer milestone activity types and count logs
    completion_stats = []
    for at in activity_types:
        if at.is_milestone:
            cnt = ActivityLog.query.filter_by(
                quest_id=quest_id, activity_type_id=at.id, reversed=False
            ).count()
            completion_stats.append({"name": at.name, "count": cnt})

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
        chains_completed=chains_completed,
        earning_progress=earning_progress,
        completion_stats=completion_stats,
        achievements=achievements,
        recent_logs=recent_logs,
        activity_count=activity_count,
        journal_completions=journal_completions,
        purchases=purchases,
        bonuses=bonuses,
        journal=journal,
        activity_types=activity_types,
        ctx=ctx,
        is_admin=is_admin,
    )


@bp.route("/member/<int:member_id>")
def member_select(member_id):
    """Show active quests for a member to pick."""
    member = _get_or_404(Member, member_id)
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
    member = _get_or_404(Member, member_id)
    stats = lifetime.get_all_stats(member_id)

    unlocks = AchievementUnlock.query.filter_by(member_id=member_id).order_by(AchievementUnlock.unlocked_at.desc()).all()
    achievements = []
    for u in unlocks:
        ach = db.session.get(Achievement, u.achievement_id)
        achievements.append({"achievement": ach, "unlocked_at": u.unlocked_at})

    # Precompute quest history with stats
    all_quests = Quest.query.filter_by(member_id=member_id).order_by(Quest.created_at.desc()).all()
    quest_history = []
    for q in all_quests:
        earned = ledger.get_lifetime_earned(q.id)
        levels = QuestLevel.query.filter_by(quest_id=q.id).order_by(QuestLevel.threshold).all()
        current_level = None
        for lv in levels:
            if earned >= lv.threshold:
                current_level = lv.name
        quest_history.append({
            "quest": q,
            "earned": earned,
            "current_level": current_level,
            "level_count": len(levels),
            "levels_unlocked": sum(1 for lv in levels if earned >= lv.threshold),
        })

    # Avatar gallery (seed current avatar into gallery if not already there)
    gallery = MemberAvatar.query.filter_by(member_id=member_id).order_by(MemberAvatar.created_at.desc()).all()
    if member.avatar_url and not any(a.image_url == member.avatar_url for a in gallery):
        new_avatar = MemberAvatar(member_id=member_id, image_url=member.avatar_url)
        db.session.add(new_avatar)
        db.session.commit()
        gallery = MemberAvatar.query.filter_by(member_id=member_id).order_by(MemberAvatar.created_at.desc()).all()

    is_admin = session.get("admin", False)

    return render_template(
        "dashboard/profile.html",
        member=member,
        stats=stats,
        achievements=achievements,
        quest_history=quest_history,
        gallery=gallery,
        is_admin=is_admin,
    )


@bp.route("/member/<int:member_id>/avatar/select", methods=["POST"])
def avatar_select(member_id):
    """Player selects an avatar from their gallery."""
    member = db.session.get(Member, member_id)
    avatar_id = int(request.form["avatar_id"])
    avatar = db.session.get(MemberAvatar, avatar_id)
    if avatar and avatar.member_id == member_id:
        member.avatar_url = avatar.image_url
        db.session.commit()
    return redirect(url_for("dashboard.member_profile", member_id=member_id))


@bp.route("/member/<int:member_id>/avatar/upload", methods=["POST"])
def avatar_upload(member_id):
    """Upload a new avatar (admin only)."""
    if not session.get("admin"):
        return redirect(url_for("dashboard.member_profile", member_id=member_id))
    member = db.session.get(Member, member_id)
    from app.engines.uploads import save_uploaded_image
    uploaded = request.files.get("avatar_file")
    if uploaded and uploaded.filename:
        url = save_uploaded_image(uploaded)
        # Add to gallery
        avatar = MemberAvatar(member_id=member_id, image_url=url)
        db.session.add(avatar)
        # Set as current
        member.avatar_url = url
        db.session.commit()
    return redirect(url_for("dashboard.member_profile", member_id=member_id))


@bp.route("/member/<int:member_id>/avatar/<int:avatar_id>/delete", methods=["POST"])
def avatar_delete(member_id, avatar_id):
    """Remove an avatar from gallery (admin only). Does not delete the file."""
    if not session.get("admin"):
        return redirect(url_for("dashboard.member_profile", member_id=member_id))
    member = db.session.get(Member, member_id)
    avatar = db.session.get(MemberAvatar, avatar_id)
    if avatar and avatar.member_id == member_id:
        # If this was the active avatar, clear it
        if member.avatar_url == avatar.image_url:
            member.avatar_url = None
        db.session.delete(avatar)
        db.session.commit()
    return redirect(url_for("dashboard.member_profile", member_id=member_id))


@bp.route("/quest/<int:quest_id>/history")
def quest_history(quest_id):
    """Activity log timeline for a specific quest."""
    quest = db.session.get(Quest, quest_id)
    if not quest:
        abort(404)
    logs = ActivityLog.query.filter_by(quest_id=quest_id, reversed=False).order_by(ActivityLog.logged_at.desc()).all()
    ctx = quest_engine.get_quest_context(quest_id)

    # Side quest completions for history
    standalone_completions = SideQuestCompletion.query.filter_by(quest_id=quest_id).join(
        SideQuestCompletion.side_quest
    ).filter(
        SideQuestCompletion.reversed_at.is_(None),
        db.text("side_quests.chain_id IS NULL"),
    ).order_by(SideQuestCompletion.completed_at.desc()).all()

    completed_chains = SideQuestChain.query.filter_by(quest_id=quest_id).filter(
        SideQuestChain.completed_at.isnot(None)
    ).order_by(SideQuestChain.completed_at.desc()).all()

    journal_completions = []
    for c in standalone_completions:
        journal_completions.append({"type": "side_quest", "name": c.side_quest.name, "reward": c.side_quest.currency_reward, "prize": c.side_quest.prize_description, "date": c.completed_at})
    for chain in completed_chains:
        journal_completions.append({"type": "chain", "name": chain.name, "reward": chain.currency_reward, "prize": chain.prize_description, "date": chain.completed_at})
    journal_completions.sort(key=lambda x: x["date"], reverse=True)

    # Shop purchases for history
    purchases = ShopPurchase.query.filter_by(quest_id=quest_id).order_by(ShopPurchase.purchased_at.desc()).all()

    # Bonus awards
    bonuses = Transaction.query.filter_by(quest_id=quest_id, type="adjustment").order_by(Transaction.created_at.desc()).all()

    return render_template(
        "dashboard/history.html",
        quest=quest,
        logs=logs,
        journal_completions=journal_completions,
        purchases=purchases,
        bonuses=bonuses,
        ctx=ctx,
    )


@bp.route("/campaign/<int:campaign_id>")
def campaign_view(campaign_id):
    """Campaign overview scorecard — game-show style party display."""
    campaign = _get_or_404(Campaign, campaign_id)
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


@bp.route("/quest/<int:quest_id>/shop")
def quest_shop(quest_id):
    """Dedicated Treasure Shop page."""
    quest = db.session.get(Quest, quest_id)
    if not quest:
        abort(404)
    member = quest.member
    campaign = db.session.get(Campaign, quest.campaign_id) if quest.campaign_id else None
    balance = ledger.get_balance(quest_id)

    # Combined shop items: quest-owned + campaign-owned (only available)
    shop_items = ShopItem.query.filter_by(quest_id=quest_id, is_available=True).order_by(ShopItem.cost).all()
    if campaign:
        campaign_shop = ShopItem.query.filter_by(campaign_id=campaign.id, is_available=True).order_by(ShopItem.cost).all()
        shop_items = shop_items + campaign_shop
        shop_items.sort(key=lambda x: x.cost)

    # Purchase history
    purchases = ShopPurchase.query.filter_by(quest_id=quest_id).order_by(ShopPurchase.purchased_at.desc()).all()

    # Theme context
    ctx = quest_engine.get_quest_context(quest_id)

    # Admin check
    is_admin = session.get("admin", False)

    affordable_count = sum(1 for item in shop_items if balance >= item.cost)

    return render_template(
        "dashboard/shop.html",
        quest=quest,
        campaign=campaign,
        member=member,
        balance=balance,
        shop_items=shop_items,
        purchases=purchases,
        ctx=ctx,
        is_admin=is_admin,
        affordable_count=affordable_count,
    )


@bp.route("/quest/<int:quest_id>/redeem", methods=["POST"])
def redeem(quest_id):
    """Self-service shop redemption (no admin required)."""
    item_id = request.form.get("item_id", type=int)
    quest = db.session.get(Quest, quest_id)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if item_id is None or not quest:
        msg = "Invalid item or quest"
        if is_ajax:
            return jsonify(success=False, message=msg), 400
        flash(msg, "error")
        return redirect(url_for("dashboard.index"))

    success, msg, _purchase = shop_engine.redeem_item(quest_id, item_id, quest.campaign_id)
    if success:
        if is_ajax:
            new_balance = ledger.get_balance(quest_id)
            return jsonify(success=True, message=msg, balance=new_balance)
        flash(msg, "success")
    else:
        if is_ajax:
            status = 403 if "belong" in msg else 400
            return jsonify(success=False, message=msg), status
        flash(msg, "error")

    return redirect(url_for("dashboard.quest_shop", quest_id=quest_id))
