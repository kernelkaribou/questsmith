import json
import math
from functools import wraps
from datetime import date, datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app, send_from_directory, jsonify, abort

from app import db
from app.models import (
    Member, Campaign, Quest, ActivityType, EarningRule,
    PartyGoal, QuestLevel, ShopItem, SideQuest, SideQuestChain, Achievement,
    ShopPurchase, Transaction, SideQuestCompletion,
)
from app.engines import quest as quest_engine
from app.engines import ledger, achievement as achievement_engine, side_quest as side_quest_engine, shop as shop_engine
from app.engines.uploads import save_uploaded_image

bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin.login", next=request.path))
        return f(*args, **kwargs)
    return decorated


def _is_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def admin_success(message, redirect_url, payload=None):
    """Return success response: JSON for AJAX, flash+redirect for non-JS."""
    if _is_ajax():
        data = {"success": True, "message": message}
        if payload:
            data.update(payload)
        return jsonify(data)
    flash(message, "success")
    return redirect(redirect_url)


def admin_error(message, redirect_url, status=400):
    """Return error response: JSON for AJAX, flash+redirect for non-JS."""
    if _is_ajax():
        return jsonify(success=False, message=message), status
    flash(message, "error")
    return redirect(redirect_url)


def _get_or_404(model, id):
    obj = db.session.get(model, id)
    if obj is None:
        abort(404)
    return obj


def _parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _parse_date(date_str):
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None


def _form_int(name, default=None, min_val=None):
    """Parse a form integer, returning default if missing/invalid."""
    val = request.form.get(name, "").strip()
    if not val:
        return default
    try:
        result = int(val)
        if min_val is not None and result < min_val:
            return default
        return result
    except (ValueError, TypeError):
        return default


def _safe_int(raw):
    """Parse an arbitrary value to int, returning None if invalid."""
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


# --- Auth ---

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        next_url = request.form.get("next") or url_for("admin.index")
    else:
        next_url = request.args.get("next") or url_for("admin.index")
    # Ensure next_url is a local path (not external redirect)
    if not next_url.startswith("/"):
        next_url = url_for("admin.index")
    if request.method == "POST":
        pin = request.form.get("pin", "")
        if pin == current_app.config["ADMIN_PIN"]:
            session["admin"] = True
            return redirect(next_url)
        flash("Incorrect PIN", "error")
    return render_template("admin/login.html", next_url=next_url)


@bp.route("/logout")
def logout():
    session.pop("admin", None)
    next_url = request.args.get("next") or request.referrer or url_for("dashboard.index")
    return redirect(next_url)


# --- Dashboard ---

@bp.route("/")
@admin_required
def index():
    quests = Quest.query.filter_by(status="active").all()
    campaigns = Campaign.query.filter_by(status="active").all()
    members = Member.query.all()
    return render_template("admin/index.html", quests=quests, campaigns=campaigns, members=members)


# --- Members ---

@bp.route("/members")
@admin_required
def members():
    return render_template("admin/members.html", members=Member.query.all())


@bp.route("/members/new", methods=["GET", "POST"])
@admin_required
def member_create():
    if request.method == "POST":
        avatar_url = request.form.get("avatar_url") or None
        uploaded = request.files.get("avatar_file")
        if uploaded and uploaded.filename:
            avatar_url = save_uploaded_image(uploaded)

        member = Member(
            name=request.form["name"],
            avatar_url=avatar_url,
        )
        db.session.add(member)
        db.session.commit()
        flash(f"Member '{member.name}' created", "success")
        return redirect(url_for("admin.members"))
    return render_template("admin/member_form.html", member=None)


@bp.route("/members/<int:member_id>/edit", methods=["GET", "POST"])
@admin_required
def member_edit(member_id):
    member = db.session.get(Member, member_id)
    if request.method == "POST":
        member.name = request.form["name"]
        uploaded = request.files.get("avatar_file")
        if uploaded and uploaded.filename:
            member.avatar_url = save_uploaded_image(uploaded)
        elif request.form.get("avatar_url"):
            member.avatar_url = request.form["avatar_url"]
        db.session.commit()
        flash("Member updated", "success")
        return redirect(url_for("admin.members"))
    return render_template("admin/member_form.html", member=member)


# --- Quests (the core unit) ---

@bp.route("/quests/new", methods=["GET", "POST"])
@admin_required
def quest_create():
    if request.method == "POST":
        graphic_url = request.form.get("theme_graphic_url") or None
        uploaded = request.files.get("theme_graphic_file")
        if uploaded and uploaded.filename:
            graphic_url = save_uploaded_image(uploaded)

        campaign_id = request.form.get("campaign_id") or None
        if campaign_id:
            campaign_id = int(campaign_id)

        # Enforce one active quest per member per campaign
        member_id = int(request.form["member_id"])
        if campaign_id:
            conflict = Quest.query.filter(
                Quest.member_id == member_id,
                Quest.campaign_id == campaign_id,
                Quest.status == "active",
            ).first()
            if conflict:
                flash("That member already has an active quest in this campaign.", "error")
                members = Member.query.all()
                campaigns = Campaign.query.filter_by(status="active").all()
                return render_template("admin/quest_form.html", quest=None, members=members, campaigns=campaigns)

        completion_target = request.form.get("completion_target") or None
        if completion_target:
            completion_target = int(completion_target)
        completion_bonus = int(request.form.get("completion_bonus") or 0)

        quest = Quest(
            member_id=member_id,
            campaign_id=campaign_id,
            theme_name=request.form["theme_name"],
            theme_graphic_url=graphic_url,
            color_primary=request.form.get("color_primary", "#4F46E5"),
            color_secondary=request.form.get("color_secondary", "#818CF8"),
            color_background=request.form.get("color_background", "#1e293b"),
            currency_label=request.form.get("currency_label") or None,
            progress_label=request.form.get("progress_label") or None,
            party_goal_label=request.form.get("party_goal_label") or None,
            level_label=request.form.get("level_label") or None,
            shop_label=request.form.get("shop_label") or None,
            chest_label=request.form.get("chest_label") or None,
            completion_target=completion_target,
            completion_bonus=completion_bonus,
        )
        db.session.add(quest)
        db.session.flush()

        # Create initial activity type + earning rule if provided
        activity_name = request.form.get("new_activity_name")
        if activity_name:
            from app.models import ActivityType, EarningRule
            is_milestone = bool(request.form.get("new_activity_milestone"))
            unit_label = "completion" if is_milestone else (request.form.get("new_activity_unit") or "units")
            at = ActivityType(
                quest_id=quest.id,
                name=activity_name,
                unit_label=unit_label,
                is_milestone=is_milestone,
            )
            db.session.add(at)
            db.session.flush()

            rule_reward = request.form.get("new_rule_reward")
            rule_qty = "1" if is_milestone else request.form.get("new_rule_qty")
            if rule_qty and rule_reward:
                rule = EarningRule(
                    activity_type_id=at.id,
                    rule_type="per_log" if is_milestone else "per_batch",
                    quantity_required=int(rule_qty),
                    currency_reward=int(rule_reward),
                )
                db.session.add(rule)

        db.session.commit()
        flash(f"Quest '{quest.theme_name}' created", "success")
        return redirect(url_for("admin.quest_edit", quest_id=quest.id))
    members = Member.query.all()
    campaigns = Campaign.query.filter_by(status="active").all()
    preselect_campaign = request.args.get("campaign_id")
    return render_template("admin/quest_form.html", quest=None, members=members, campaigns=campaigns, preselect_campaign=preselect_campaign)


@bp.route("/quests/<int:quest_id>")
@admin_required
def quest_detail(quest_id):
    quest = _get_or_404(Quest, quest_id)
    balance = ledger.get_balance(quest_id)
    lifetime_earned = ledger.get_lifetime_earned(quest_id)

    sibling_quests = []
    if quest.campaign_id:
        sibling_quests = (
            Quest.query.filter_by(campaign_id=quest.campaign_id, status="active")
            .order_by(Quest.id)
            .all()
        )

    # Combined shop: quest-owned + campaign-owned (if linked)
    shop_items = ShopItem.query.filter_by(quest_id=quest_id).order_by(ShopItem.sort_order).all()
    if quest.campaign_id:
        campaign_shop = ShopItem.query.filter_by(campaign_id=quest.campaign_id).order_by(ShopItem.sort_order).all()
        shop_items = shop_items + campaign_shop

    return render_template(
        "admin/quest_detail.html",
        quest=quest,
        balance=balance,
        lifetime_earned=lifetime_earned,
        sibling_quests=sibling_quests,
        levels=QuestLevel.query.filter_by(quest_id=quest_id).order_by(QuestLevel.sort_order).all(),
        side_quests=SideQuest.query.filter_by(quest_id=quest_id, chain_id=None).order_by(SideQuest.sort_order).all(),
        chains=side_quest_engine.get_available_chains(quest_id),
        all_chains=SideQuestChain.query.filter_by(quest_id=quest_id).order_by(SideQuestChain.sort_order).all(),
        completions=SideQuestCompletion.query.filter_by(quest_id=quest_id).order_by(SideQuestCompletion.completed_at.desc()).limit(20).all(),
        shop_items=shop_items,
        recent_logs=quest.activity_logs.order_by(db.text("logged_at DESC")).limit(10).all(),
    )


@bp.route("/quests/<int:quest_id>/edit", methods=["GET", "POST"])
@admin_required
def quest_edit(quest_id):
    quest = _get_or_404(Quest, quest_id)
    if request.method == "POST":
        # Handle member reassignment
        new_member_id = int(request.form["member_id"])
        if new_member_id != quest.member_id:
            # Enforce one active quest per member per campaign
            campaign_id = request.form.get("campaign_id") or None
            if campaign_id:
                conflict = Quest.query.filter(
                    Quest.member_id == new_member_id,
                    Quest.campaign_id == int(campaign_id),
                    Quest.status == "active",
                    Quest.id != quest.id,
                ).first()
                if conflict:
                    flash("That member already has an active quest in this campaign.", "error")
                    members = Member.query.all()
                    campaigns = Campaign.query.filter_by(status="active").all()
                    return render_template("admin/quest_form.html", quest=quest, members=members, campaigns=campaigns)
            quest.member_id = new_member_id

        quest.theme_name = request.form["theme_name"]
        quest.color_primary = request.form.get("color_primary", "#4F46E5")
        quest.color_secondary = request.form.get("color_secondary", "#818CF8")
        quest.color_background = request.form.get("color_background", "#1e293b")
        quest.currency_label = request.form.get("currency_label") or None
        quest.progress_label = request.form.get("progress_label") or None
        quest.party_goal_label = request.form.get("party_goal_label") or None
        quest.level_label = request.form.get("level_label") or None
        quest.shop_label = request.form.get("shop_label") or None
        quest.chest_label = request.form.get("chest_label") or None

        # Completion settings
        completion_target = request.form.get("completion_target")
        quest.completion_target = int(completion_target) if completion_target else None
        completion_bonus = request.form.get("completion_bonus")
        quest.completion_bonus = int(completion_bonus) if completion_bonus else 0

        campaign_id = request.form.get("campaign_id") or None
        quest.campaign_id = int(campaign_id) if campaign_id else None

        # Handle graphic upload or URL
        uploaded = request.files.get("theme_graphic_file")
        if uploaded and uploaded.filename:
            quest.theme_graphic_url = save_uploaded_image(uploaded)
        elif request.form.get("theme_graphic_url"):
            quest.theme_graphic_url = request.form["theme_graphic_url"]

        # Edit existing earning rules. Reward is always editable; quantity is
        # only submitted for measured activities (disabled for completions).
        # Only rules belonging to this quest may be modified.
        owned_rule_ids = {
            rule.id for at in quest.activity_types for rule in at.earning_rules
        }
        for key, value in request.form.items():
            if key.startswith("rule_reward_") and value:
                rule_id = _safe_int(key.replace("rule_reward_", ""))
                if rule_id in owned_rule_ids:
                    rule = db.session.get(EarningRule, rule_id)
                    if rule:
                        rule.currency_reward = int(value)
            elif key.startswith("rule_qty_") and value:
                rule_id = _safe_int(key.replace("rule_qty_", ""))
                if rule_id in owned_rule_ids:
                    rule = db.session.get(EarningRule, rule_id)
                    if rule:
                        rule.quantity_required = int(value)

        # Update existing activity types: name (editable), milestone toggle
        for at in quest.activity_types:
            new_name = (request.form.get(f"at_name_{at.id}") or "").strip()
            if new_name:
                at.name = new_name
            new_milestone = f"milestone_{at.id}" in request.form
            was_milestone = at.is_milestone
            at.is_milestone = new_milestone
            if new_milestone:
                # Completions are always a single flat reward per log. Normalize
                # defensively on every save (not only on toggle) so any legacy
                # rows with a stale per_batch rule_type or quantity_required > 1
                # are corrected and earn correctly.
                if not at.unit_label:
                    at.unit_label = "completion"
                for rule in at.earning_rules:
                    rule.rule_type = "per_log"
                    rule.quantity_required = 1
            elif was_milestone:
                # Toggled off — revert to cumulative measured behavior.
                for rule in at.earning_rules:
                    rule.rule_type = "per_batch"

        db.session.commit()
        flash("Quest updated", "success")
        return redirect(url_for("admin.quest_detail", quest_id=quest.id))
    members = Member.query.all()
    campaigns = Campaign.query.filter_by(status="active").all()
    return render_template("admin/quest_form.html", quest=quest, members=members, campaigns=campaigns)


# --- Activity Type Management ---

@bp.route("/quests/<int:quest_id>/activity-types/new", methods=["POST"])
@admin_required
def activity_type_create(quest_id):
    """Add a new activity type to a quest."""
    quest = db.session.get(Quest, quest_id)
    if not quest:
        return admin_error("Quest not found", url_for("admin.index"))

    name = request.form.get("new_activity_name")
    is_milestone = "new_activity_milestone" in request.form
    unit = request.form.get("new_activity_unit")
    if is_milestone:
        unit = unit or "completion"
    if not name or not unit:
        return admin_error("Name and unit are required", url_for("admin.quest_edit", quest_id=quest_id))

    at = ActivityType(quest_id=quest.id, name=name, unit_label=unit, is_milestone=is_milestone)
    db.session.add(at)
    db.session.flush()

    new_reward = request.form.get("new_rule_reward")
    new_qty = "1" if is_milestone else request.form.get("new_rule_qty")
    if new_qty and new_reward:
        rule = EarningRule(
            activity_type_id=at.id,
            rule_type="per_log" if is_milestone else "per_batch",
            quantity_required=int(new_qty),
            currency_reward=int(new_reward),
        )
        db.session.add(rule)

    db.session.commit()
    redirect_url = url_for("admin.quest_edit", quest_id=quest_id)
    return admin_success(f"Added activity type: {name}", redirect_url)


@bp.route("/activity-type/<int:at_id>/delete", methods=["POST"])
@admin_required
def activity_type_delete(at_id):
    """Remove an activity type from a quest."""
    at = db.session.get(ActivityType, at_id)
    if not at:
        return admin_error("Activity type not found", url_for("admin.index"))

    quest_id = at.quest_id
    redirect_url = url_for("admin.quest_detail", quest_id=quest_id)

    log_count = at.activity_logs.count()
    if log_count > 0:
        return admin_error(f"Cannot delete: {log_count} activities already logged with this type", redirect_url)

    for rule in at.earning_rules:
        db.session.delete(rule)
    db.session.delete(at)
    db.session.commit()
    return admin_success(f"Removed activity type: {at.name}", redirect_url)


# --- Delete Routes for Config Entities ---

@bp.route("/level/<int:level_id>/delete", methods=["POST"])
@admin_required
def level_delete(level_id):
    """Delete a quest level."""
    level = db.session.get(QuestLevel, level_id)
    if not level:
        return admin_error("Level not found", url_for("admin.index"))

    quest_id = level.quest_id
    redirect_url = url_for("admin.quest_detail", quest_id=quest_id)

    # Delete associated unlocks
    from app.models import QuestLevelUnlock
    QuestLevelUnlock.query.filter_by(level_id=level_id).delete()
    db.session.delete(level)
    db.session.commit()
    return admin_success(f"Removed level: {level.name}", redirect_url)


@bp.route("/side-quest/<int:sq_id>/delete", methods=["POST"])
@admin_required
def side_quest_delete(sq_id):
    """Delete a side quest (standalone or chain step)."""
    from app.models import SideQuestCompletion
    sq = db.session.get(SideQuest, sq_id)
    if not sq:
        return admin_error("Side quest not found", url_for("admin.index"))

    quest_id = sq.quest_id
    redirect_url = url_for("admin.quest_detail", quest_id=quest_id)

    completions = SideQuestCompletion.query.filter_by(side_quest_id=sq_id).count()
    if completions > 0:
        return admin_error(f"Cannot delete: {completions} completions exist", redirect_url)

    db.session.delete(sq)
    db.session.commit()
    return admin_success(f"Removed side quest: {sq.name}", redirect_url)


@bp.route("/chain/<int:chain_id>/delete", methods=["POST"])
@admin_required
def chain_delete(chain_id):
    """Delete a quest chain and its steps (if no completions)."""
    from app.models import SideQuestCompletion
    chain = db.session.get(SideQuestChain, chain_id)
    if not chain:
        return admin_error("Chain not found", url_for("admin.index"))

    quest_id = chain.quest_id
    redirect_url = url_for("admin.quest_detail", quest_id=quest_id)

    # Check if any step has completions
    step_ids = [s.id for s in chain.steps]
    if step_ids:
        completions = SideQuestCompletion.query.filter(
            SideQuestCompletion.side_quest_id.in_(step_ids)
        ).count()
        if completions > 0:
            return admin_error(f"Cannot delete: chain steps have {completions} completions", redirect_url)

    # Delete steps then chain
    for step in chain.steps:
        db.session.delete(step)
    db.session.delete(chain)
    db.session.commit()
    return admin_success(f"Removed chain: {chain.name}", redirect_url)


@bp.route("/shop-item/<int:item_id>/delete", methods=["POST"])
@admin_required
def shop_item_delete(item_id):
    """Delete a shop item if no purchases exist."""
    item = db.session.get(ShopItem, item_id)
    if not item:
        return admin_error("Shop item not found", url_for("admin.index"))

    redirect_url = url_for("admin.quest_detail", quest_id=item.quest_id) if item.quest_id else url_for("admin.campaign_detail", campaign_id=item.campaign_id)

    purchases = ShopPurchase.query.filter_by(shop_item_id=item_id).count()
    if purchases > 0:
        return admin_error(f"Cannot delete: {purchases} purchases exist for this item", redirect_url)

    db.session.delete(item)
    db.session.commit()
    return admin_success(f"Removed shop item: {item.name}", redirect_url)


@bp.route("/earning-rule/<int:rule_id>/delete", methods=["POST"])
@admin_required
def earning_rule_delete(rule_id):
    """Delete an earning rule if no transactions reference it."""
    rule = db.session.get(EarningRule, rule_id)
    if not rule:
        return admin_error("Earning rule not found", url_for("admin.index"))

    quest_id = rule.activity_type.quest_id
    redirect_url = url_for("admin.quest_detail", quest_id=quest_id)

    txn_count = Transaction.query.filter_by(earning_rule_id=rule_id).count()
    if txn_count > 0:
        return admin_error(f"Cannot delete: {txn_count} transactions use this rule", redirect_url)

    db.session.delete(rule)
    db.session.commit()
    return admin_success("Removed earning rule", redirect_url)


@bp.route("/party-goal/<int:goal_id>/delete", methods=["POST"])
@admin_required
def party_goal_delete(goal_id):
    """Delete a party goal."""
    goal = db.session.get(PartyGoal, goal_id)
    if not goal:
        return admin_error("Party goal not found", url_for("admin.index"))

    campaign_id = goal.campaign_id
    db.session.delete(goal)
    db.session.commit()
    return admin_success(f"Removed party goal: {goal.name}", url_for("admin.campaign_detail", campaign_id=campaign_id))


# --- Delete/Archive for Top-Level Entities ---

@bp.route("/member/<int:member_id>/delete", methods=["POST"])
@admin_required
def member_delete(member_id):
    """Delete a member if they have no quests."""
    member = db.session.get(Member, member_id)
    if not member:
        return admin_error("Member not found", url_for("admin.index"))

    quest_count = Quest.query.filter_by(member_id=member_id).count()
    if quest_count > 0:
        return admin_error(f"Cannot delete: member has {quest_count} quest(s). Archive or remove quests first.", url_for("admin.members"))

    db.session.delete(member)
    db.session.commit()
    return admin_success(f"Removed member: {member.name}", url_for("admin.members"))


@bp.route("/achievement/<int:ach_id>/delete", methods=["POST"])
@admin_required
def achievement_delete(ach_id):
    """Delete an achievement if no one has unlocked it."""
    from app.models import AchievementUnlock
    ach = db.session.get(Achievement, ach_id)
    if not ach:
        return admin_error("Achievement not found", url_for("admin.index"))

    unlocks = AchievementUnlock.query.filter_by(achievement_id=ach_id).count()
    if unlocks > 0:
        return admin_error(f"Cannot delete: {unlocks} members have unlocked this", url_for("admin.achievements_list"))

    db.session.delete(ach)
    db.session.commit()
    return admin_success(f"Removed achievement: {ach.name}", url_for("admin.achievements_list"))


@bp.route("/quest/<int:quest_id>/archive", methods=["POST"])
@admin_required
def quest_archive(quest_id):
    """Archive a quest (soft-delete). Hard delete only if empty."""
    quest = db.session.get(Quest, quest_id)
    if not quest:
        return admin_error("Quest not found", url_for("admin.index"))

    redirect_url = url_for("admin.index")
    log_count = quest.activity_logs.count()

    if log_count == 0 and request.form.get("hard_delete"):
        # Safe to hard delete — no activity
        name = quest.theme_name
        # Clean up nested entities
        ActivityType.query.filter_by(quest_id=quest_id).delete()
        QuestLevel.query.filter_by(quest_id=quest_id).delete()
        SideQuest.query.filter_by(quest_id=quest_id).delete()
        ShopItem.query.filter_by(quest_id=quest_id).delete()
        SideQuestChain.query.filter_by(quest_id=quest_id).delete()
        db.session.delete(quest)
        db.session.commit()
        return admin_success(f"Deleted quest: {name}", redirect_url)

    quest.status = "archived"
    db.session.commit()
    return admin_success(f"Archived quest: {quest.theme_name}", redirect_url)


@bp.route("/campaign/<int:campaign_id>/archive", methods=["POST"])
@admin_required
def campaign_archive(campaign_id):
    """Archive a campaign (soft-delete). Hard delete only if no quests."""
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return admin_error("Campaign not found", url_for("admin.index"))

    redirect_url = url_for("admin.index")
    quest_count = Quest.query.filter_by(campaign_id=campaign_id).count()

    if quest_count == 0 and request.form.get("hard_delete"):
        name = campaign.name
        PartyGoal.query.filter_by(campaign_id=campaign_id).delete()
        ShopItem.query.filter_by(campaign_id=campaign_id).delete()
        db.session.delete(campaign)
        db.session.commit()
        return admin_success(f"Deleted campaign: {name}", redirect_url)

    campaign.status = "archived"
    db.session.commit()
    return admin_success(f"Archived campaign: {campaign.name}", redirect_url)


# --- Activity Log Undo ---

@bp.route("/activity-log/<int:log_id>/undo", methods=["POST"])
@admin_required
def activity_log_undo(log_id):
    """Undo an activity log entry by creating reversal transactions."""
    from app.models import ActivityLog
    log = _get_or_404(ActivityLog, log_id)

    quest_id = log.quest_id
    redirect_url = url_for("admin.quest_detail", quest_id=quest_id)

    if log.reversed:
        return admin_error("This activity has already been reversed", redirect_url)

    # Create reversal transactions for each earn transaction from this log
    transactions = Transaction.query.filter_by(activity_log_id=log.id, type="earn").all()
    for txn in transactions:
        reversal = Transaction(
            quest_id=quest_id,
            type="reversal",
            amount=txn.amount,
            description=f"Reversal: {txn.description or log.activity_type.name}",
            activity_log_id=log.id,
        )
        db.session.add(reversal)

    # Mark the log as reversed
    log.reversed = True
    db.session.flush()

    # Reconcile per_batch earning rules: reversed log may have contributed quantity
    # to batches paid on other logs, requiring additional reversals
    from app.engines.quest import _reconcile_batch_overpayment
    _reconcile_batch_overpayment(quest_id, log.activity_type_id)

    # Recalculate quest completion state
    quest = _get_or_404(Quest, quest_id)
    if quest.completed_at:
        lifetime = ledger.get_lifetime_earned(quest_id)
        if quest.completion_target and lifetime < quest.completion_target:
            # Remove completion bonus if it exists
            bonus_txns = Transaction.query.filter_by(
                quest_id=quest_id, type="completion_bonus"
            ).all()
            for bt in bonus_txns:
                reversal = Transaction(
                    quest_id=quest_id,
                    type="reversal",
                    amount=bt.amount,
                    description="Reversal: Quest completion bonus (quest re-opened)",
                )
                db.session.add(reversal)
            quest.completed_at = None

    # Remove level unlocks that are no longer valid
    from app.engines.validation import revoke_invalid_unlocks
    revoke_invalid_unlocks(quest_id)

    db.session.commit()
    return admin_success(f"Reversed activity: {log.quantity} {log.activity_type.unit_label}", redirect_url)


# --- Bonus Awards ---

@bp.route("/quests/<int:quest_id>/bonus", methods=["POST"])
@admin_required
def award_bonus(quest_id):
    """Award bonus currency (adjustment) to a quest."""
    quest = _get_or_404(Quest, quest_id)
    redirect_url = request.form.get("next") or url_for("admin.quest_detail", quest_id=quest_id)

    amount = _form_int("amount", min_val=1)
    reason = request.form.get("reason", "").strip()
    if not reason:
        return admin_error("Reason is required", redirect_url)

    txn = Transaction(
        quest_id=quest_id,
        type="adjustment",
        amount=amount,
        description=f"Bonus: {reason}",
    )
    db.session.add(txn)
    db.session.commit()

    return admin_success(f"Awarded {amount} bonus ({reason})", redirect_url)


# --- Activity Logging ---

@bp.route("/log", methods=["GET", "POST"])
@admin_required
def log_activity():
    if request.method == "POST":
        next_url = request.form.get("next") or url_for("admin.log_activity")
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        description = request.form.get("description") or None
        notes = request.form.get("notes") or None

        def _fail(message):
            if is_ajax:
                return jsonify(success=False, message=message), 400
            flash(message, "error")
            return redirect(next_url)

        quest_id = _safe_int(request.form.get("quest_id"))
        if quest_id is None:
            return _fail("Quest not found")
        quest = db.session.get(Quest, quest_id)
        if not quest:
            return _fail("Quest not found")

        # The dropdown selection may be a measured OR a completion activity.
        primary_id = _safe_int(request.form.get("activity_type_id")) if (request.form.get("activity_type_id") or "").strip() else None
        primary_type = None
        if primary_id is not None:
            primary_type = db.session.get(ActivityType, primary_id)
            if not primary_type or primary_type.quest_id != quest_id:
                return _fail("Invalid activity type")

        # Determine which activity is measured and which are completions.
        # A measured activity needs a quantity; completions are logged once each.
        measured_type = None
        seen_ids = set()
        completion_types = []
        if primary_type:
            if primary_type.is_milestone:
                completion_types.append(primary_type)
                seen_ids.add(primary_type.id)
            else:
                measured_type = primary_type

        # Optional extra completion checkboxes (deduped, must be completions).
        for raw in request.form.getlist("milestones"):
            mid = _safe_int(raw)
            if mid is None:
                return _fail("Invalid completion selection")
            if mid in seen_ids:
                continue
            seen_ids.add(mid)
            ct = db.session.get(ActivityType, mid)
            if not ct or ct.quest_id != quest_id or not ct.is_milestone:
                return _fail("Invalid completion selection")
            completion_types.append(ct)

        if not measured_type and not completion_types:
            return _fail("Select an activity to log")

        txns = []
        quantity = None
        if measured_type:
            quantity = _form_int("quantity", min_val=1)
            if quantity is None:
                return _fail("Quantity must be a positive integer")
            primary_log, p_txns = quest_engine.log_activity(
                quest_id, measured_type.id, quantity, description, notes
            )
            if not primary_log:
                return _fail("Failed to log activity")
            txns.extend(p_txns)

        for ct in completion_types:
            _c_log, c_txns = quest_engine.log_activity(quest_id, ct.id, 1, notes=notes)
            txns.extend(c_txns)

        achievement_engine.check_achievements(quest.member_id)
        db.session.commit()

        earned = sum(t.amount for t in txns)

        # Build a message from whatever was actually logged
        parts = []
        if measured_type:
            parts.append(f"{quantity} {measured_type.unit_label}")
        if completion_types:
            parts.append(f"{len(completion_types)} completion{'s' if len(completion_types) != 1 else ''}")
        logged_desc = " + ".join(parts)

        progress_msg = ""
        if measured_type:
            progress = quest_engine.get_earning_progress(quest_id)
            at_progress = [p for p in progress if p["activity_type"].id == measured_type.id]
            if at_progress:
                p = at_progress[0]
                progress_msg = f" ({p['units_to_next']} {p['activity_type'].unit_label} to next)"

        quest = db.session.get(Quest, quest_id)
        completion_msg = " QUEST COMPLETE!" if quest.completed_at else ""

        msg = f"Logged {logged_desc} - earned {earned} currency{progress_msg}{completion_msg}"
        if is_ajax:
            return jsonify(success=True, message=msg)
        flash(msg, "success")
        return redirect(next_url)

    quests = Quest.query.filter_by(status="active").all()
    for q in quests:
        q.activity_types_json = json.dumps([
            {"id": at.id, "name": at.name, "unit": at.unit_label, "is_milestone": at.is_milestone}
            for at in q.activity_types
        ])
    return render_template("admin/log_activity.html", quests=quests)

# --- Redemption ---

@bp.route("/quests/<int:quest_id>/redeem", methods=["POST"])
@admin_required
def redeem(quest_id):
    item_id = _form_int("item_id", min_val=1)
    quest = db.session.get(Quest, quest_id)
    item = db.session.get(ShopItem, item_id) if item_id is not None else None
    if not item or not quest:
        return admin_error("Item or quest not found", url_for("admin.index"))
    if item.quest_id and item.quest_id != quest_id:
        return admin_error("Item does not belong to this quest", url_for("admin.quest_detail", quest_id=quest_id))
    if item.campaign_id and item.campaign_id != quest.campaign_id:
        return admin_error("Item does not belong to this campaign", url_for("admin.quest_detail", quest_id=quest_id))

    next_url = request.form.get("next") or url_for("admin.quest_detail", quest_id=quest_id)
    success, msg, _purchase = shop_engine.redeem_item(quest_id, item_id, quest.campaign_id)
    if success:
        success_msg = f"{quest.member.name} redeemed '{item.name}'"
        if item.cost == 0:
            success_msg += " (free)"
        return admin_success(success_msg, next_url)
    return admin_error(msg, next_url)


@bp.route("/purchases/<int:purchase_id>/refund", methods=["POST"])
@admin_required
def refund_purchase(purchase_id):
    """Refund a shop purchase: credit currency back, mark as refunded."""
    purchase = db.session.get(ShopPurchase, purchase_id)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if not purchase or purchase.refunded_at:
        msg = "Purchase not found or already refunded"
        if is_ajax:
            return jsonify(success=False, message=msg), 400
        flash(msg, "error")
        next_url = request.form.get("next") or url_for("admin.index")
        return redirect(next_url)

    quest_id = purchase.quest_id
    item = purchase.shop_item

    # Credit the currency back (refund type: included in balance, excluded from lifetime/party)
    if item.cost > 0:
        txn = Transaction(
            quest_id=quest_id,
            type="refund",
            amount=item.cost,
            description=f"Refund: {item.name}",
        )
        db.session.add(txn)

    # Mark as refunded
    purchase.refunded_at = datetime.now(timezone.utc)
    db.session.commit()
    msg = f"Refunded '{item.name}' (+{item.cost} returned)"
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(success=True, message=msg)
    flash(msg, "success")

    next_url = request.form.get("next") or url_for("admin.quest_detail", quest_id=quest_id)
    return redirect(next_url)


# --- Side Quest Award ---

@bp.route("/quests/<int:quest_id>/side-quest/<int:side_quest_id>/award", methods=["POST"])
@admin_required
def side_quest_award(quest_id, side_quest_id):
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    result = side_quest_engine.complete_side_quest(side_quest_id, quest_id)
    if result:
        db.session.commit()
        sq = db.session.get(SideQuest, side_quest_id)
        msg = f"Side quest '{sq.name}' awarded!"
        if is_ajax:
            return jsonify(success=True, message=msg)
        flash(msg, "success")
    else:
        msg = "Side quest not available (already completed or on cooldown)"
        if is_ajax:
            return jsonify(success=False, message=msg), 400
        flash(msg, "error")
    next_url = request.form.get("next") or url_for("admin.quest_detail", quest_id=quest_id)
    return redirect(next_url)


@bp.route("/quests/<int:quest_id>/completion/<int:completion_id>/reverse", methods=["POST"])
@admin_required
def completion_reverse(quest_id, completion_id):
    """Reverse a side quest or chain step completion."""
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    result = side_quest_engine.reverse_completion(completion_id)
    if result:
        # Remove level unlocks that are no longer valid
        from app.engines.validation import revoke_invalid_unlocks
        revoke_invalid_unlocks(quest_id)
        db.session.commit()
        msg = "Completion reversed"
        if result["chain_reopened"]:
            msg += " (chain reopened)"
        if is_ajax:
            return jsonify(success=True, message=msg)
        flash(msg, "success")
    else:
        msg = "Completion not found or already reversed"
        if is_ajax:
            return jsonify(success=False, message=msg), 400
        flash(msg, "error")
    next_url = request.form.get("next") or url_for("admin.quest_detail", quest_id=quest_id)
    return redirect(next_url)

@bp.route("/quests/<int:quest_id>/levels/new", methods=["GET", "POST"])
@admin_required
def level_create(quest_id):
    quest = _get_or_404(Quest, quest_id)
    if request.method == "POST":
        threshold = _form_int("threshold", min_val=1)
        if threshold is None:
            return admin_error("Threshold must be a positive integer", url_for("admin.level_create", quest_id=quest_id))
        level = QuestLevel(
            quest_id=quest.id,
            name=request.form["name"],
            threshold=threshold,
            reward_description=request.form.get("reward_description") or None,
        )
        db.session.add(level)
        db.session.commit()
        flash("Quest Level created", "success")
        return redirect(url_for("admin.quest_detail", quest_id=quest_id))
    return render_template("admin/generic_form.html", type_name="Quest Level", item=None, quest_id=quest_id)


@bp.route("/levels/<int:level_id>/edit", methods=["GET", "POST"])
@admin_required
def level_edit(level_id):
    level = _get_or_404(QuestLevel, level_id)
    if request.method == "POST":
        threshold = _form_int("threshold", min_val=1)
        if threshold is None:
            return admin_error("Threshold must be a positive integer", url_for("admin.level_edit", level_id=level_id))
        level.name = request.form["name"]
        level.threshold = threshold
        level.reward_description = request.form.get("reward_description") or None
        db.session.commit()
        flash("Quest Level updated", "success")
        return redirect(url_for("admin.quest_detail", quest_id=level.quest_id))
    return render_template("admin/generic_form.html", type_name="Quest Level", item=level, quest_id=level.quest_id)


# --- Side Quests (belong to quest) ---

@bp.route("/quests/<int:quest_id>/side-quests/new", methods=["GET", "POST"])
@admin_required
def side_quest_create(quest_id):
    _get_or_404(Quest, quest_id)
    if request.method == "POST":
        sq = SideQuest(
            quest_id=quest_id,
            name=request.form["name"],
            description=request.form.get("description") or None,
            currency_reward=int(request.form.get("currency_reward") or 0),
            prize_description=request.form.get("prize_description") or None,
            repeat_type=request.form.get("repeat_type", "one_time"),
            expires_at=_parse_datetime(request.form.get("expires_at")),
        )
        db.session.add(sq)
        db.session.commit()
        flash("Side Quest created", "success")
        return redirect(url_for("admin.quest_detail", quest_id=quest_id))
    return render_template("admin/generic_form.html", type_name="Side Quest", item=None, quest_id=quest_id)


@bp.route("/side-quests/<int:side_quest_id>/edit", methods=["GET", "POST"])
@admin_required
def side_quest_edit(side_quest_id):
    sq = _get_or_404(SideQuest, side_quest_id)
    if request.method == "POST":
        sq.name = request.form["name"]
        sq.description = request.form.get("description") or None
        sq.currency_reward = int(request.form.get("currency_reward") or 0)
        sq.prize_description = request.form.get("prize_description") or None
        sq.repeat_type = request.form.get("repeat_type", "one_time")
        sq.expires_at = _parse_datetime(request.form.get("expires_at"))
        db.session.commit()
        flash("Side Quest updated", "success")
        return redirect(url_for("admin.quest_detail", quest_id=sq.quest_id))
    return render_template("admin/generic_form.html", type_name="Side Quest", item=sq, quest_id=sq.quest_id)


# --- Side Quest Chains ---

@bp.route("/quests/<int:quest_id>/chains/new", methods=["GET", "POST"])
@admin_required
def chain_create(quest_id):
    quest = _get_or_404(Quest, quest_id)
    if request.method == "POST":
        chain = SideQuestChain(
            quest_id=quest.id,
            name=request.form["name"],
            description=request.form.get("description") or None,
            currency_reward=int(request.form.get("currency_reward") or 0),
            prize_description=request.form.get("prize_description") or None,
            visibility_mode=request.form.get("visibility_mode", "checklist_sequential"),
            expires_at=_parse_datetime(request.form.get("expires_at")),
        )
        db.session.add(chain)
        db.session.commit()
        flash("Chain created", "success")
        return redirect(url_for("admin.chain_detail", chain_id=chain.id))
    return render_template("admin/chain_form.html", chain=None, quest_id=quest_id)


@bp.route("/chains/<int:chain_id>")
@admin_required
def chain_detail(chain_id):
    chain = _get_or_404(SideQuestChain, chain_id)
    status = side_quest_engine.get_chain_status(chain, chain.quest_id)
    return render_template("admin/chain_detail.html", chain=chain, status=status, now=datetime.now(timezone.utc))


@bp.route("/chains/<int:chain_id>/edit", methods=["GET", "POST"])
@admin_required
def chain_edit(chain_id):
    chain = _get_or_404(SideQuestChain, chain_id)
    if request.method == "POST":
        chain.name = request.form["name"]
        chain.description = request.form.get("description") or None
        chain.currency_reward = int(request.form.get("currency_reward") or 0)
        chain.prize_description = request.form.get("prize_description") or None
        chain.visibility_mode = request.form.get("visibility_mode", "checklist_sequential")
        chain.expires_at = _parse_datetime(request.form.get("expires_at"))
        db.session.commit()
        flash("Chain updated", "success")
        return redirect(url_for("admin.chain_detail", chain_id=chain.id))
    return render_template("admin/chain_form.html", chain=chain, quest_id=chain.quest_id)


@bp.route("/chains/<int:chain_id>/steps/new", methods=["GET", "POST"])
@admin_required
def chain_step_create(chain_id):
    chain = _get_or_404(SideQuestChain, chain_id)
    if request.method == "POST":
        max_order = db.session.query(db.func.max(SideQuest.chain_order)).filter_by(chain_id=chain_id).scalar() or 0
        step = SideQuest(
            quest_id=chain.quest_id,
            chain_id=chain_id,
            chain_order=max_order + 1,
            name=request.form["name"],
            description=request.form.get("description") or None,
            currency_reward=0,
            repeat_type="one_time",
        )
        db.session.add(step)
        db.session.commit()
        flash(f"Step added: {step.name}", "success")
        return redirect(url_for("admin.chain_detail", chain_id=chain_id))
    return render_template("admin/chain_step_form.html", chain=chain, step=None)


@bp.route("/chains/<int:chain_id>/steps/<int:step_id>/edit", methods=["GET", "POST"])
@admin_required
def chain_step_edit(chain_id, step_id):
    chain = _get_or_404(SideQuestChain, chain_id)
    step = _get_or_404(SideQuest, step_id)
    if step.chain_id != chain.id:
        abort(404)
    if request.method == "POST":
        step.name = request.form["name"]
        step.description = request.form.get("description") or None
        if request.form.get("chain_order"):
            step.chain_order = int(request.form["chain_order"])
        db.session.commit()
        flash("Step updated", "success")
        return redirect(url_for("admin.chain_detail", chain_id=chain_id))
    return render_template("admin/chain_step_form.html", chain=chain, step=step)


@bp.route("/chains/<int:chain_id>/steps/<int:step_id>/complete", methods=["POST"])
@admin_required
def chain_step_complete(chain_id, step_id):
    chain = _get_or_404(SideQuestChain, chain_id)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    result = side_quest_engine.complete_chain_step(step_id, chain.quest_id)
    if result:
        db.session.commit()
        if result["chain_completed"]:
            msg = f"Chain '{chain.name}' completed! Reward awarded."
        else:
            step = _get_or_404(SideQuest, step_id)
            if step.chain_id != chain.id:
                abort(404)
            msg = f"Step '{step.name}' completed!"
        if is_ajax:
            return jsonify(success=True, message=msg)
        flash(msg, "success")
    else:
        msg = "Step not available"
        if is_ajax:
            return jsonify(success=False, message=msg), 400
        flash(msg, "error")
    next_url = request.form.get("next") or url_for("admin.chain_detail", chain_id=chain_id)
    return redirect(next_url)


# --- Quest Shop Items (belong to quest) ---

@bp.route("/quests/<int:quest_id>/shop/new", methods=["GET", "POST"])
@admin_required
def quest_shop_item_create(quest_id):
    _get_or_404(Quest, quest_id)
    if request.method == "POST":
        cost = _form_int("cost", min_val=0)
        if cost is None:
            return admin_error("Cost must be zero or greater", url_for("admin.quest_shop_item_create", quest_id=quest_id))
        image_url = request.form.get("image_url") or None
        uploaded = request.files.get("image_file")
        if uploaded and uploaded.filename:
            image_url = save_uploaded_image(uploaded)

        item = ShopItem(
            quest_id=quest_id,
            name=request.form["name"],
            cost=cost,
            image_url=image_url,
        )
        db.session.add(item)
        db.session.commit()
        flash("Shop item created", "success")
        return redirect(url_for("admin.quest_detail", quest_id=quest_id))
    return render_template("admin/generic_form.html", type_name="Shop Item", item=None, quest_id=quest_id)


# --- Campaigns (optional grouping) ---

@bp.route("/campaigns")
@admin_required
def campaigns():
    return render_template("admin/campaigns.html", campaigns=Campaign.query.all())


@bp.route("/campaigns/new", methods=["GET", "POST"])
@admin_required
def campaign_create():
    if request.method == "POST":
        campaign = Campaign(
            name=request.form["name"],
            description=request.form.get("description") or None,
            start_date=_parse_date(request.form.get("start_date")),
            end_date=_parse_date(request.form.get("end_date")),
            status=request.form.get("status", "active"),
        )
        db.session.add(campaign)
        db.session.commit()
        flash(f"Campaign '{campaign.name}' created", "success")
        return redirect(url_for("admin.campaign_detail", campaign_id=campaign.id))
    return render_template("admin/campaign_form.html", campaign=None)


@bp.route("/campaigns/<int:campaign_id>")
@admin_required
def campaign_detail(campaign_id):
    import markdown2
    campaign = db.session.get(Campaign, campaign_id)
    quests = Quest.query.filter_by(campaign_id=campaign_id).all()
    balances = {q.id: ledger.get_balance(q.id) for q in quests}
    notes_html = markdown2.markdown(campaign.notes, extras=["fenced-code-blocks", "tables"], safe_mode="escape") if campaign.notes else ""
    return render_template(
        "admin/campaign_detail.html",
        campaign=campaign,
        quests=quests,
        balances=balances,
        notes_html=notes_html,
        party_goals=PartyGoal.query.filter_by(campaign_id=campaign_id).order_by(PartyGoal.sort_order).all(),
        shop_items=ShopItem.query.filter_by(campaign_id=campaign_id).order_by(ShopItem.sort_order).all(),
    )


@bp.route("/campaigns/<int:campaign_id>/edit", methods=["GET", "POST"])
@admin_required
def campaign_edit(campaign_id):
    campaign = db.session.get(Campaign, campaign_id)
    if request.method == "POST":
        campaign.name = request.form["name"]
        campaign.description = request.form.get("description") or None
        campaign.start_date = _parse_date(request.form.get("start_date"))
        campaign.end_date = _parse_date(request.form.get("end_date"))
        campaign.status = request.form.get("status", "active")
        db.session.commit()
        flash("Campaign updated", "success")
        return redirect(url_for("admin.campaign_detail", campaign_id=campaign_id))
    return render_template("admin/campaign_form.html", campaign=campaign)


@bp.route("/campaigns/<int:campaign_id>/notes", methods=["GET", "POST"])
@admin_required
def campaign_notes(campaign_id):
    campaign = _get_or_404(Campaign, campaign_id)
    if request.method == "POST":
        campaign.notes = request.form.get("notes") or None
        db.session.commit()
        flash("Notes saved", "success")
        return redirect(url_for("admin.campaign_detail", campaign_id=campaign_id))
    return render_template("admin/campaign_notes.html", campaign=campaign)


# --- Party Goals (belong to campaign) ---

@bp.route("/campaigns/<int:campaign_id>/party-goals/new", methods=["GET", "POST"])
@admin_required
def party_goal_create(campaign_id):
    _get_or_404(Campaign, campaign_id)
    if request.method == "POST":
        target = _form_int("target_amount", min_val=1)
        if target is None:
            return admin_error("Target amount must be a positive integer", url_for("admin.party_goal_create", campaign_id=campaign_id))
        num_members = db.session.query(Quest.member_id).filter_by(campaign_id=campaign_id).distinct().count()
        min_contrib = math.ceil(target / num_members) if num_members > 0 else target
        goal = PartyGoal(
            campaign_id=campaign_id,
            name=request.form["name"],
            description=request.form.get("description") or None,
            target_amount=target,
            min_individual_contribution=min_contrib,
        )
        db.session.add(goal)
        db.session.commit()
        flash("Party Goal created", "success")
        return redirect(url_for("admin.campaign_detail", campaign_id=campaign_id))
    return render_template("admin/generic_form.html", type_name="Party Goal", item=None, campaign_id=campaign_id)


@bp.route("/party-goals/<int:goal_id>/edit", methods=["GET", "POST"])
@admin_required
def party_goal_edit(goal_id):
    goal = _get_or_404(PartyGoal, goal_id)
    if request.method == "POST":
        target_amount = _form_int("target_amount", min_val=1)
        if target_amount is None:
            return admin_error("Target amount must be a positive integer", url_for("admin.party_goal_edit", goal_id=goal_id))
        goal.name = request.form["name"]
        goal.description = request.form.get("description") or None
        goal.target_amount = target_amount
        num_members = db.session.query(Quest.member_id).filter_by(campaign_id=goal.campaign_id).distinct().count()
        goal.min_individual_contribution = math.ceil(goal.target_amount / num_members) if num_members > 0 else goal.target_amount
        db.session.commit()
        flash("Party Goal updated", "success")
        return redirect(url_for("admin.campaign_detail", campaign_id=goal.campaign_id))
    return render_template("admin/generic_form.html", type_name="Party Goal", item=goal, campaign_id=goal.campaign_id)


# --- Campaign Shared Shop Items ---

@bp.route("/campaigns/<int:campaign_id>/shop/new", methods=["GET", "POST"])
@admin_required
def campaign_shop_item_create(campaign_id):
    _get_or_404(Campaign, campaign_id)
    if request.method == "POST":
        cost = _form_int("cost", min_val=0)
        if cost is None:
            return admin_error("Cost must be zero or greater", url_for("admin.campaign_shop_item_create", campaign_id=campaign_id))
        image_url = request.form.get("image_url") or None
        uploaded = request.files.get("image_file")
        if uploaded and uploaded.filename:
            image_url = save_uploaded_image(uploaded)

        item = ShopItem(
            campaign_id=campaign_id,
            name=request.form["name"],
            cost=cost,
            image_url=image_url,
        )
        db.session.add(item)
        db.session.commit()
        flash("Shared shop item created", "success")
        return redirect(url_for("admin.campaign_detail", campaign_id=campaign_id))
    return render_template("admin/generic_form.html", type_name="Shop Item", item=None, campaign_id=campaign_id)


@bp.route("/shop/<int:item_id>/edit", methods=["GET", "POST"])
@admin_required
def shop_item_edit(item_id):
    item = db.session.get(ShopItem, item_id)
    if request.method == "POST":
        cost = _form_int("cost", min_val=0)
        if cost is None:
            return admin_error("Cost must be zero or greater", url_for("admin.shop_item_edit", item_id=item_id))
        item.name = request.form["name"]
        item.cost = cost
        uploaded = request.files.get("image_file")
        if uploaded and uploaded.filename:
            item.image_url = save_uploaded_image(uploaded)
        elif request.form.get("image_url"):
            item.image_url = request.form["image_url"]
        db.session.commit()
        flash("Shop item updated", "success")
        # Redirect based on owner
        if item.campaign_id:
            return redirect(url_for("admin.campaign_detail", campaign_id=item.campaign_id))
        return redirect(url_for("admin.quest_detail", quest_id=item.quest_id))
    owner_id = item.campaign_id if item.campaign_id else None
    return render_template("admin/generic_form.html", type_name="Shop Item", item=item,
                           campaign_id=item.campaign_id, quest_id=item.quest_id)


# --- Achievements ---

@bp.route("/achievements")
@admin_required
def achievements_list():
    return render_template("admin/achievements.html", achievements=Achievement.query.all())


@bp.route("/achievements/new", methods=["GET", "POST"])
@admin_required
def achievement_create():
    if request.method == "POST":
        trigger_type = request.form.get("trigger_type", "manual")
        trigger_condition = None
        if trigger_type == "auto":
            metric = request.form.get("trigger_metric")
            threshold = request.form.get("trigger_threshold")
            if metric and threshold:
                trigger_condition = {"metric": metric, "threshold": int(threshold)}

        ach = Achievement(
            name=request.form["name"],
            description=request.form.get("description") or None,
            icon=request.form.get("icon") or None,
            trigger_type=trigger_type,
            trigger_condition=trigger_condition,
        )
        db.session.add(ach)
        db.session.commit()
        flash("Achievement created", "success")
        return redirect(url_for("admin.achievements_list"))
    return render_template("admin/achievement_form.html", achievement=None)


@bp.route("/achievements/<int:achievement_id>/edit", methods=["GET", "POST"])
@admin_required
def achievement_edit(achievement_id):
    ach = db.session.get(Achievement, achievement_id)
    if request.method == "POST":
        ach.name = request.form["name"]
        ach.description = request.form.get("description") or None
        ach.icon = request.form.get("icon") or None
        ach.trigger_type = request.form.get("trigger_type", "manual")
        if ach.trigger_type == "auto":
            metric = request.form.get("trigger_metric")
            threshold = request.form.get("trigger_threshold")
            if metric and threshold:
                ach.trigger_condition = {"metric": metric, "threshold": int(threshold)}
        else:
            ach.trigger_condition = None
        db.session.commit()
        flash("Achievement updated", "success")
        return redirect(url_for("admin.achievements_list"))
    return render_template("admin/achievement_form.html", achievement=ach)


@bp.route("/achievements/<int:achievement_id>/award", methods=["GET", "POST"])
@admin_required
def achievement_award(achievement_id):
    ach = db.session.get(Achievement, achievement_id)
    if request.method == "POST":
        member_id = int(request.form["member_id"])
        unlock = achievement_engine.manually_award(achievement_id, member_id)
        if unlock:
            db.session.commit()
            flash(f"Achievement awarded to member", "success")
        else:
            flash("Already awarded to this member", "error")
        return redirect(url_for("admin.achievements_list"))
    members = Member.query.all()
    return render_template("admin/achievement_award.html", achievement=ach, members=members)


# --- Image Uploads ---

@bp.route("/uploads/<path:filepath>")
def serve_upload(filepath):
    import os
    if ".." in filepath or filepath.startswith("/"):
        abort(404)
    upload_root = os.path.join(current_app.root_path, "..", "data", "uploads")
    upload_root = os.path.abspath(upload_root)
    full_path = os.path.abspath(os.path.join(upload_root, filepath))
    if not full_path.startswith(upload_root):
        abort(404)
    return send_from_directory(upload_root, filepath)
