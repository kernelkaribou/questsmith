import json
import math
from functools import wraps
from datetime import date, datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app, send_from_directory, jsonify

from app import db
from app.models import (
    Member, Journey, Quest, ActivityType, EarningRule,
    PartyGoal, QuestLevel, ShopItem, SideQuest, SideQuestChain, Achievement,
    ShopPurchase, Transaction,
)
from app.engines import quest as quest_engine
from app.engines import ledger, achievement as achievement_engine, side_quest as side_quest_engine
from app.engines.uploads import save_uploaded_image

bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return decorated


# --- Auth ---

@bp.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.args.get("next") or request.form.get("next") or url_for("admin.index")
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
    journeys = Journey.query.filter_by(status="active").all()
    members = Member.query.all()
    return render_template("admin/index.html", quests=quests, journeys=journeys, members=members)


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

        journey_id = request.form.get("journey_id") or None
        if journey_id:
            journey_id = int(journey_id)

        completion_target = request.form.get("completion_target") or None
        if completion_target:
            completion_target = int(completion_target)
        completion_bonus = int(request.form.get("completion_bonus") or 0)

        quest = Quest(
            member_id=int(request.form["member_id"]),
            journey_id=journey_id,
            theme_name=request.form["theme_name"],
            theme_graphic_url=graphic_url,
            color_primary=request.form.get("color_primary", "#4F46E5"),
            color_secondary=request.form.get("color_secondary", "#818CF8"),
            currency_label=request.form.get("currency_label") or None,
            progress_label=request.form.get("progress_label") or None,
            party_goal_label=request.form.get("party_goal_label") or None,
            completion_target=completion_target,
            completion_bonus=completion_bonus,
        )
        db.session.add(quest)
        db.session.flush()

        # Create initial activity type + earning rule if provided
        activity_name = request.form.get("new_activity_name")
        if activity_name:
            from app.models import ActivityType, EarningRule
            unit_label = request.form.get("new_activity_unit") or "units"
            is_milestone = bool(request.form.get("new_activity_milestone"))
            at = ActivityType(
                quest_id=quest.id,
                name=activity_name,
                unit_label=unit_label,
                is_milestone=is_milestone,
            )
            db.session.add(at)
            db.session.flush()

            rule_qty = request.form.get("new_rule_qty")
            rule_reward = request.form.get("new_rule_reward")
            if rule_qty and rule_reward:
                rule = EarningRule(
                    activity_type_id=at.id,
                    quantity_required=int(rule_qty),
                    currency_reward=int(rule_reward),
                )
                db.session.add(rule)

        db.session.commit()
        flash(f"Quest '{quest.theme_name}' created", "success")
        return redirect(url_for("admin.quest_edit", quest_id=quest.id))
    members = Member.query.all()
    journeys = Journey.query.filter_by(status="active").all()
    preselect_journey = request.args.get("journey_id")
    return render_template("admin/quest_form.html", quest=None, members=members, journeys=journeys, preselect_journey=preselect_journey)


@bp.route("/quests/<int:quest_id>")
@admin_required
def quest_detail(quest_id):
    quest = db.session.get(Quest, quest_id)
    balance = ledger.get_balance(quest_id)
    lifetime_earned = ledger.get_lifetime_earned(quest_id)

    # Combined shop: quest-owned + journey-owned (if linked)
    shop_items = ShopItem.query.filter_by(quest_id=quest_id).order_by(ShopItem.sort_order).all()
    if quest.journey_id:
        journey_shop = ShopItem.query.filter_by(journey_id=quest.journey_id).order_by(ShopItem.sort_order).all()
        shop_items = shop_items + journey_shop

    return render_template(
        "admin/quest_detail.html",
        quest=quest,
        balance=balance,
        lifetime_earned=lifetime_earned,
        levels=QuestLevel.query.filter_by(quest_id=quest_id).order_by(QuestLevel.sort_order).all(),
        side_quests=SideQuest.query.filter_by(quest_id=quest_id, chain_id=None).order_by(SideQuest.sort_order).all(),
        chains=side_quest_engine.get_available_chains(quest_id),
        all_chains=SideQuestChain.query.filter_by(quest_id=quest_id).order_by(SideQuestChain.sort_order).all(),
        shop_items=shop_items,
        recent_logs=quest.activity_logs.order_by(db.text("logged_at DESC")).limit(10).all(),
    )


@bp.route("/quests/<int:quest_id>/edit", methods=["GET", "POST"])
@admin_required
def quest_edit(quest_id):
    quest = db.session.get(Quest, quest_id)
    if request.method == "POST":
        quest.theme_name = request.form["theme_name"]
        quest.color_primary = request.form.get("color_primary", "#4F46E5")
        quest.color_secondary = request.form.get("color_secondary", "#818CF8")
        quest.currency_label = request.form.get("currency_label") or None
        quest.progress_label = request.form.get("progress_label") or None
        quest.party_goal_label = request.form.get("party_goal_label") or None

        # Completion settings
        completion_target = request.form.get("completion_target")
        quest.completion_target = int(completion_target) if completion_target else None
        completion_bonus = request.form.get("completion_bonus")
        quest.completion_bonus = int(completion_bonus) if completion_bonus else 0

        journey_id = request.form.get("journey_id") or None
        quest.journey_id = int(journey_id) if journey_id else None

        # Handle graphic upload or URL
        uploaded = request.files.get("theme_graphic_file")
        if uploaded and uploaded.filename:
            quest.theme_graphic_url = save_uploaded_image(uploaded)
        elif request.form.get("theme_graphic_url"):
            quest.theme_graphic_url = request.form["theme_graphic_url"]

        # Add new activity type if provided
        new_name = request.form.get("new_activity_name")
        new_unit = request.form.get("new_activity_unit")
        if new_name and new_unit:
            is_milestone = "new_activity_milestone" in request.form
            at = ActivityType(quest_id=quest.id, name=new_name, unit_label=new_unit, is_milestone=is_milestone)
            db.session.add(at)
            db.session.flush()
            new_qty = request.form.get("new_rule_qty")
            new_reward = request.form.get("new_rule_reward")
            if new_qty and new_reward:
                rule = EarningRule(
                    activity_type_id=at.id,
                    rule_type="per_log" if is_milestone else "per_batch",
                    quantity_required=int(new_qty),
                    currency_reward=int(new_reward),
                )
                db.session.add(rule)

        # Edit existing earning rules
        for key, value in request.form.items():
            if key.startswith("rule_qty_") and value:
                rule_id = int(key.replace("rule_qty_", ""))
                rule = db.session.get(EarningRule, rule_id)
                if rule:
                    rule.quantity_required = int(value)
                    reward_key = f"rule_reward_{rule_id}"
                    if reward_key in request.form and request.form[reward_key]:
                        rule.currency_reward = int(request.form[reward_key])

        db.session.commit()
        flash("Quest updated", "success")
        return redirect(url_for("admin.quest_detail", quest_id=quest.id))
    members = Member.query.all()
    journeys = Journey.query.filter_by(status="active").all()
    return render_template("admin/quest_form.html", quest=quest, members=members, journeys=journeys)


# --- Activity Type Management ---

@bp.route("/activity-type/<int:at_id>/delete", methods=["POST"])
@admin_required
def activity_type_delete(at_id):
    """Remove an activity type from a quest."""
    at = db.session.get(ActivityType, at_id)
    if not at:
        flash("Activity type not found", "error")
        return redirect(url_for("admin.index"))

    quest_id = at.quest_id
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    # Check if there are logged activities using this type
    log_count = at.activity_logs.count()
    if log_count > 0:
        msg = f"Cannot delete: {log_count} activities already logged with this type"
        if is_ajax:
            return jsonify(success=False, message=msg), 400
        flash(msg, "error")
        return redirect(url_for("admin.quest_detail", quest_id=quest_id))

    # Delete earning rules first, then the activity type
    for rule in at.earning_rules:
        db.session.delete(rule)
    db.session.delete(at)
    db.session.commit()

    msg = f"Removed activity type: {at.name}"
    if is_ajax:
        return jsonify(success=True, message=msg)
    flash(msg, "success")
    return redirect(url_for("admin.quest_detail", quest_id=quest_id))


# --- Activity Logging ---

@bp.route("/log", methods=["GET", "POST"])
@admin_required
def log_activity():
    if request.method == "POST":
        quest_id = int(request.form["quest_id"])
        activity_type_id = int(request.form["activity_type_id"])
        quantity = int(request.form["quantity"])
        description = request.form.get("description") or None
        notes = request.form.get("notes") or None

        if quantity <= 0:
            flash("Quantity must be greater than zero", "error")
            return redirect(request.form.get("next") or url_for("admin.log_activity"))

        log, txns = quest_engine.log_activity(quest_id, activity_type_id, quantity, description, notes)
        if log:
            quest = db.session.get(Quest, quest_id)

            # Handle milestone checkboxes
            milestone_ids = request.form.getlist("milestones")
            for mid in milestone_ids:
                m_log, m_txns = quest_engine.log_activity(quest_id, int(mid), 1, notes=f"Milestone (with {quantity} {log.activity_type.unit_label})")
                txns.extend(m_txns)

            achievement_engine.check_achievements(quest.member_id)
            db.session.commit()

            earned = sum(t.amount for t in txns)
            # Show progress toward next currency
            progress = quest_engine.get_earning_progress(quest_id)
            at_progress = [p for p in progress if p["activity_type"].id == activity_type_id]
            progress_msg = ""
            if at_progress:
                p = at_progress[0]
                progress_msg = f" ({p['units_to_next']} {p['activity_type'].unit_label} to next)"
            milestone_msg = f" + {len(milestone_ids)} milestone(s)" if milestone_ids else ""

            # Check for quest completion notification
            quest = db.session.get(Quest, quest_id)
            completion_msg = ""
            if quest.completed_at:
                completion_msg = " QUEST COMPLETE!"

            msg = f"Logged {quantity} - earned {earned} currency{progress_msg}{milestone_msg}{completion_msg}"
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify(success=True, message=msg)
            flash(msg, "success")
        else:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify(success=False, message="Failed to log activity"), 400
            flash("Failed to log activity", "error")

        next_url = request.form.get("next") or url_for("admin.log_activity")
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
    item_id = int(request.form["item_id"])
    item = db.session.get(ShopItem, item_id)
    quest = db.session.get(Quest, quest_id)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if item.cost == 0:
        purchase = ShopPurchase(shop_item_id=item.id, quest_id=quest_id, transaction_id=None)
        db.session.add(purchase)
        db.session.commit()
        msg = f"{quest.member.name} redeemed '{item.name}' (free)"
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
            msg = f"{quest.member.name} redeemed '{item.name}'"
            if is_ajax:
                return jsonify(success=True, message=msg)
            flash(msg, "success")
        else:
            msg = f"Insufficient balance for '{item.name}'"
            if is_ajax:
                return jsonify(success=False, message=msg), 400
            flash(msg, "error")

    next_url = request.form.get("next") or url_for("admin.quest_detail", quest_id=quest_id)
    return redirect(next_url)


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


# --- Quest Levels (belong to quest) ---

@bp.route("/quests/<int:quest_id>/levels/new", methods=["GET", "POST"])
@admin_required
def level_create(quest_id):
    if request.method == "POST":
        level = QuestLevel(
            quest_id=quest_id,
            name=request.form["name"],
            threshold=int(request.form["threshold"]),
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
    level = db.session.get(QuestLevel, level_id)
    if request.method == "POST":
        level.name = request.form["name"]
        level.threshold = int(request.form["threshold"])
        level.reward_description = request.form.get("reward_description") or None
        db.session.commit()
        flash("Quest Level updated", "success")
        return redirect(url_for("admin.quest_detail", quest_id=level.quest_id))
    return render_template("admin/generic_form.html", type_name="Quest Level", item=level, quest_id=level.quest_id)


# --- Side Quests (belong to quest) ---

@bp.route("/quests/<int:quest_id>/side-quests/new", methods=["GET", "POST"])
@admin_required
def side_quest_create(quest_id):
    if request.method == "POST":
        sq = SideQuest(
            quest_id=quest_id,
            name=request.form["name"],
            description=request.form.get("description") or None,
            currency_reward=int(request.form["currency_reward"]),
            repeat_type=request.form.get("repeat_type", "one_time"),
        )
        db.session.add(sq)
        db.session.commit()
        flash("Side Quest created", "success")
        return redirect(url_for("admin.quest_detail", quest_id=quest_id))
    return render_template("admin/generic_form.html", type_name="Side Quest", item=None, quest_id=quest_id)


@bp.route("/side-quests/<int:side_quest_id>/edit", methods=["GET", "POST"])
@admin_required
def side_quest_edit(side_quest_id):
    sq = db.session.get(SideQuest, side_quest_id)
    if request.method == "POST":
        sq.name = request.form["name"]
        sq.description = request.form.get("description") or None
        sq.currency_reward = int(request.form["currency_reward"])
        sq.repeat_type = request.form.get("repeat_type", "one_time")
        db.session.commit()
        flash("Side Quest updated", "success")
        return redirect(url_for("admin.quest_detail", quest_id=sq.quest_id))
    return render_template("admin/generic_form.html", type_name="Side Quest", item=sq, quest_id=sq.quest_id)


# --- Side Quest Chains ---

@bp.route("/quests/<int:quest_id>/chains/new", methods=["GET", "POST"])
@admin_required
def chain_create(quest_id):
    if request.method == "POST":
        chain = SideQuestChain(
            quest_id=quest_id,
            name=request.form["name"],
            description=request.form.get("description") or None,
            currency_reward=int(request.form["currency_reward"]),
            visibility_mode=request.form.get("visibility_mode", "checklist_sequential"),
            expires_at=_parse_date(request.form.get("expires_at")),
        )
        db.session.add(chain)
        db.session.commit()
        flash("Chain created", "success")
        return redirect(url_for("admin.chain_detail", chain_id=chain.id))
    return render_template("admin/chain_form.html", chain=None, quest_id=quest_id)


@bp.route("/chains/<int:chain_id>")
@admin_required
def chain_detail(chain_id):
    chain = db.session.get(SideQuestChain, chain_id)
    status = side_quest_engine.get_chain_status(chain, chain.quest_id)
    return render_template("admin/chain_detail.html", chain=chain, status=status)


@bp.route("/chains/<int:chain_id>/edit", methods=["GET", "POST"])
@admin_required
def chain_edit(chain_id):
    chain = db.session.get(SideQuestChain, chain_id)
    if request.method == "POST":
        chain.name = request.form["name"]
        chain.description = request.form.get("description") or None
        chain.currency_reward = int(request.form["currency_reward"])
        chain.visibility_mode = request.form.get("visibility_mode", "checklist_sequential")
        chain.expires_at = _parse_date(request.form.get("expires_at"))
        db.session.commit()
        flash("Chain updated", "success")
        return redirect(url_for("admin.chain_detail", chain_id=chain.id))
    return render_template("admin/chain_form.html", chain=chain, quest_id=chain.quest_id)


@bp.route("/chains/<int:chain_id>/steps/new", methods=["GET", "POST"])
@admin_required
def chain_step_create(chain_id):
    chain = db.session.get(SideQuestChain, chain_id)
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
    chain = db.session.get(SideQuestChain, chain_id)
    step = db.session.get(SideQuest, step_id)
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
    chain = db.session.get(SideQuestChain, chain_id)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    result = side_quest_engine.complete_chain_step(step_id, chain.quest_id)
    if result:
        db.session.commit()
        if result["chain_completed"]:
            msg = f"Chain '{chain.name}' completed! Reward awarded."
        else:
            step = db.session.get(SideQuest, step_id)
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


def _parse_date(value):
    """Parse a date string from form input, returning None if empty."""
    if not value:
        return None
    from datetime import datetime, timezone
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


# --- Quest Shop Items (belong to quest) ---

@bp.route("/quests/<int:quest_id>/shop/new", methods=["GET", "POST"])
@admin_required
def quest_shop_item_create(quest_id):
    if request.method == "POST":
        image_url = request.form.get("image_url") or None
        uploaded = request.files.get("image_file")
        if uploaded and uploaded.filename:
            image_url = save_uploaded_image(uploaded)

        item = ShopItem(
            quest_id=quest_id,
            name=request.form["name"],
            cost=int(request.form["cost"]),
            image_url=image_url,
        )
        db.session.add(item)
        db.session.commit()
        flash("Shop item created", "success")
        return redirect(url_for("admin.quest_detail", quest_id=quest_id))
    return render_template("admin/generic_form.html", type_name="Shop Item", item=None, quest_id=quest_id)


# --- Journeys (optional grouping) ---

@bp.route("/journeys")
@admin_required
def journeys():
    return render_template("admin/journeys.html", journeys=Journey.query.all())


@bp.route("/journeys/new", methods=["GET", "POST"])
@admin_required
def journey_create():
    if request.method == "POST":
        journey = Journey(
            name=request.form["name"],
            description=request.form.get("description") or None,
            start_date=_parse_date(request.form.get("start_date")),
            end_date=_parse_date(request.form.get("end_date")),
            status=request.form.get("status", "active"),
        )
        db.session.add(journey)
        db.session.commit()
        flash(f"Journey '{journey.name}' created", "success")
        return redirect(url_for("admin.journey_detail", journey_id=journey.id))
    return render_template("admin/journey_form.html", journey=None)


@bp.route("/journeys/<int:journey_id>")
@admin_required
def journey_detail(journey_id):
    journey = db.session.get(Journey, journey_id)
    quests = Quest.query.filter_by(journey_id=journey_id).all()
    balances = {q.id: ledger.get_balance(q.id) for q in quests}
    return render_template(
        "admin/journey_detail.html",
        journey=journey,
        quests=quests,
        balances=balances,
        party_goals=PartyGoal.query.filter_by(journey_id=journey_id).order_by(PartyGoal.sort_order).all(),
        shop_items=ShopItem.query.filter_by(journey_id=journey_id).order_by(ShopItem.sort_order).all(),
    )


@bp.route("/journeys/<int:journey_id>/edit", methods=["GET", "POST"])
@admin_required
def journey_edit(journey_id):
    journey = db.session.get(Journey, journey_id)
    if request.method == "POST":
        journey.name = request.form["name"]
        journey.description = request.form.get("description") or None
        journey.start_date = _parse_date(request.form.get("start_date"))
        journey.end_date = _parse_date(request.form.get("end_date"))
        journey.status = request.form.get("status", "active")
        db.session.commit()
        flash("Journey updated", "success")
        return redirect(url_for("admin.journey_detail", journey_id=journey_id))
    return render_template("admin/journey_form.html", journey=journey)


# --- Party Goals (belong to journey) ---

@bp.route("/journeys/<int:journey_id>/party-goals/new", methods=["GET", "POST"])
@admin_required
def party_goal_create(journey_id):
    if request.method == "POST":
        target = int(request.form["target_amount"])
        num_members = db.session.query(Quest.member_id).filter_by(journey_id=journey_id).distinct().count()
        min_contrib = math.ceil(target / num_members) if num_members > 0 else target
        goal = PartyGoal(
            journey_id=journey_id,
            name=request.form["name"],
            description=request.form.get("description") or None,
            target_amount=target,
            min_individual_contribution=min_contrib,
            reward_description=request.form.get("reward_description") or None,
        )
        db.session.add(goal)
        db.session.commit()
        flash("Party Goal created", "success")
        return redirect(url_for("admin.journey_detail", journey_id=journey_id))
    return render_template("admin/generic_form.html", type_name="Party Goal", item=None, journey_id=journey_id)


@bp.route("/party-goals/<int:goal_id>/edit", methods=["GET", "POST"])
@admin_required
def party_goal_edit(goal_id):
    goal = db.session.get(PartyGoal, goal_id)
    if request.method == "POST":
        goal.name = request.form["name"]
        goal.description = request.form.get("description") or None
        goal.target_amount = int(request.form["target_amount"])
        num_members = db.session.query(Quest.member_id).filter_by(journey_id=goal.journey_id).distinct().count()
        goal.min_individual_contribution = math.ceil(goal.target_amount / num_members) if num_members > 0 else goal.target_amount
        goal.reward_description = request.form.get("reward_description") or None
        db.session.commit()
        flash("Party Goal updated", "success")
        return redirect(url_for("admin.journey_detail", journey_id=goal.journey_id))
    return render_template("admin/generic_form.html", type_name="Party Goal", item=goal, journey_id=goal.journey_id)


# --- Journey Shared Shop Items ---

@bp.route("/journeys/<int:journey_id>/shop/new", methods=["GET", "POST"])
@admin_required
def journey_shop_item_create(journey_id):
    if request.method == "POST":
        image_url = request.form.get("image_url") or None
        uploaded = request.files.get("image_file")
        if uploaded and uploaded.filename:
            image_url = save_uploaded_image(uploaded)

        item = ShopItem(
            journey_id=journey_id,
            name=request.form["name"],
            cost=int(request.form["cost"]),
            image_url=image_url,
        )
        db.session.add(item)
        db.session.commit()
        flash("Shared shop item created", "success")
        return redirect(url_for("admin.journey_detail", journey_id=journey_id))
    return render_template("admin/generic_form.html", type_name="Shop Item", item=None, journey_id=journey_id)


@bp.route("/shop/<int:item_id>/edit", methods=["GET", "POST"])
@admin_required
def shop_item_edit(item_id):
    item = db.session.get(ShopItem, item_id)
    if request.method == "POST":
        item.name = request.form["name"]
        item.cost = int(request.form["cost"])
        uploaded = request.files.get("image_file")
        if uploaded and uploaded.filename:
            item.image_url = save_uploaded_image(uploaded)
        elif request.form.get("image_url"):
            item.image_url = request.form["image_url"]
        db.session.commit()
        flash("Shop item updated", "success")
        # Redirect based on owner
        if item.journey_id:
            return redirect(url_for("admin.journey_detail", journey_id=item.journey_id))
        return redirect(url_for("admin.quest_detail", quest_id=item.quest_id))
    owner_id = item.journey_id if item.journey_id else None
    return render_template("admin/generic_form.html", type_name="Shop Item", item=item,
                           journey_id=item.journey_id, quest_id=item.quest_id)


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
    upload_root = os.path.join(current_app.root_path, "..", "data", "uploads")
    upload_root = os.path.abspath(upload_root)
    directory = os.path.dirname(os.path.join(upload_root, filepath))
    filename = os.path.basename(filepath)
    return send_from_directory(directory, filename)


# --- Helpers ---

def _parse_date(date_str):
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None
