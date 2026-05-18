import json
from functools import wraps
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app

from app import db
from app.models import (
    Member, Journey, Quest, ActivityType, EarningRule,
    CoOpGoal, PrizeTier, PrizeItem, SideQuest, Achievement,
)
from app.engines import quest as quest_engine
from app.engines import ledger, achievement as achievement_engine, side_quest as side_quest_engine

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
    if request.method == "POST":
        pin = request.form.get("pin", "")
        if pin == current_app.config["ADMIN_PIN"]:
            session["admin"] = True
            return redirect(url_for("admin.index"))
        flash("Incorrect PIN", "error")
    return render_template("admin/login.html")


@bp.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect(url_for("admin.login"))


# --- Dashboard ---

@bp.route("/")
@admin_required
def index():
    journeys = Journey.query.filter_by(status="active").all()
    members = Member.query.all()
    return render_template("admin/index.html", journeys=journeys, members=members)


# --- Members ---

@bp.route("/members")
@admin_required
def members():
    return render_template("admin/members.html", members=Member.query.all())


@bp.route("/members/new", methods=["GET", "POST"])
@admin_required
def member_create():
    if request.method == "POST":
        member = Member(
            name=request.form["name"],
            avatar_url=request.form.get("avatar_url") or None,
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
        member.avatar_url = request.form.get("avatar_url") or None
        db.session.commit()
        flash("Member updated", "success")
        return redirect(url_for("admin.members"))
    return render_template("admin/member_form.html", member=member)


# --- Journeys ---

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
        coop_goals=CoOpGoal.query.filter_by(journey_id=journey_id).order_by(CoOpGoal.sort_order).all(),
        prizes=PrizeItem.query.filter_by(journey_id=journey_id).order_by(PrizeItem.sort_order).all(),
        tiers=PrizeTier.query.filter_by(journey_id=journey_id).order_by(PrizeTier.sort_order).all(),
        side_quests=SideQuest.query.filter_by(journey_id=journey_id).order_by(SideQuest.sort_order).all(),
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


# --- Quests ---

@bp.route("/journeys/<int:journey_id>/quests/new", methods=["GET", "POST"])
@admin_required
def quest_create(journey_id):
    if request.method == "POST":
        quest = Quest(
            member_id=int(request.form["member_id"]),
            journey_id=journey_id,
            theme_name=request.form["theme_name"],
            theme_graphic_url=request.form.get("theme_graphic_url") or None,
            color_primary=request.form.get("color_primary", "#4F46E5"),
            color_secondary=request.form.get("color_secondary", "#818CF8"),
            currency_label=request.form.get("currency_label") or None,
            progress_label=request.form.get("progress_label") or None,
            coop_label=request.form.get("coop_label") or None,
        )
        db.session.add(quest)
        db.session.commit()
        flash(f"Quest '{quest.theme_name}' created", "success")
        return redirect(url_for("admin.journey_detail", journey_id=journey_id))
    members = Member.query.all()
    return render_template("admin/quest_form.html", quest=None, members=members, journey_id=journey_id)


@bp.route("/quests/<int:quest_id>/edit", methods=["GET", "POST"])
@admin_required
def quest_edit(quest_id):
    quest = db.session.get(Quest, quest_id)
    if request.method == "POST":
        quest.theme_name = request.form["theme_name"]
        quest.theme_graphic_url = request.form.get("theme_graphic_url") or None
        quest.color_primary = request.form.get("color_primary", "#4F46E5")
        quest.color_secondary = request.form.get("color_secondary", "#818CF8")
        quest.currency_label = request.form.get("currency_label") or None
        quest.progress_label = request.form.get("progress_label") or None
        quest.coop_label = request.form.get("coop_label") or None

        # Add new activity type if provided
        new_name = request.form.get("new_activity_name")
        new_unit = request.form.get("new_activity_unit")
        if new_name and new_unit:
            at = ActivityType(quest_id=quest.id, name=new_name, unit_label=new_unit)
            db.session.add(at)
            db.session.flush()
            new_qty = request.form.get("new_rule_qty")
            new_reward = request.form.get("new_rule_reward")
            if new_qty and new_reward:
                rule = EarningRule(
                    activity_type_id=at.id,
                    rule_type="per_batch",
                    quantity_required=int(new_qty),
                    currency_reward=int(new_reward),
                )
                db.session.add(rule)

        db.session.commit()
        flash("Quest updated", "success")
        return redirect(url_for("admin.journey_detail", journey_id=quest.journey_id))
    return render_template("admin/quest_form.html", quest=quest, members=None, journey_id=quest.journey_id)


# --- Activity Logging ---

@bp.route("/log", methods=["GET", "POST"])
@admin_required
def log_activity():
    if request.method == "POST":
        quest_id = int(request.form["quest_id"])
        activity_type_id = int(request.form["activity_type_id"])
        quantity = int(request.form["quantity"])
        description = request.form.get("description") or None

        log, txns = quest_engine.log_activity(quest_id, activity_type_id, quantity, description)
        if log:
            # Check achievements for the member
            quest = db.session.get(Quest, quest_id)
            achievement_engine.check_achievements(quest.member_id)
            db.session.commit()

            earned = sum(t.amount for t in txns)
            flash(f"Logged {quantity} - earned {earned} currency", "success")
        else:
            flash("Failed to log activity", "error")
        return redirect(url_for("admin.log_activity"))

    # Get all active quests with their activity types as JSON
    quests = Quest.query.join(Journey).filter(Journey.status == "active").all()
    for q in quests:
        q.activity_types_json = json.dumps([
            {"id": at.id, "name": at.name, "unit": at.unit_label}
            for at in q.activity_types
        ])
    return render_template("admin/log_activity.html", quests=quests)


# --- Redemption ---

@bp.route("/quests/<int:quest_id>/redeem", methods=["POST"])
@admin_required
def redeem(quest_id):
    prize_id = int(request.form["prize_id"])
    prize = db.session.get(PrizeItem, prize_id)
    quest = db.session.get(Quest, quest_id)

    from app.models import PrizePurchase
    txn = ledger.record_spend(quest_id, prize.cost, f"Purchased: {prize.name}")
    if txn:
        db.session.flush()
        purchase = PrizePurchase(prize_item_id=prize.id, quest_id=quest_id, transaction_id=txn.id)
        db.session.add(purchase)
        db.session.commit()
        flash(f"{quest.member.name} redeemed '{prize.name}'", "success")
    else:
        flash(f"Insufficient balance for '{prize.name}'", "error")
    return redirect(url_for("admin.journey_detail", journey_id=quest.journey_id))


# --- Co-Op Goals ---

@bp.route("/journeys/<int:journey_id>/coop/new", methods=["GET", "POST"])
@admin_required
def coop_create(journey_id):
    if request.method == "POST":
        goal = CoOpGoal(
            journey_id=journey_id,
            name=request.form["name"],
            description=request.form.get("description") or None,
            target_amount=int(request.form["target_amount"]),
            min_individual_contribution=int(request.form.get("min_individual_contribution", 0)),
            reward_description=request.form.get("reward_description") or None,
        )
        db.session.add(goal)
        db.session.commit()
        flash("Co-Op Goal created", "success")
        return redirect(url_for("admin.journey_detail", journey_id=journey_id))
    return render_template("admin/generic_form.html", type_name="Co-Op Goal", item=None, journey_id=journey_id)


@bp.route("/coop/<int:goal_id>/edit", methods=["GET", "POST"])
@admin_required
def coop_edit(goal_id):
    goal = db.session.get(CoOpGoal, goal_id)
    if request.method == "POST":
        goal.name = request.form["name"]
        goal.description = request.form.get("description") or None
        goal.target_amount = int(request.form["target_amount"])
        goal.min_individual_contribution = int(request.form.get("min_individual_contribution", 0))
        goal.reward_description = request.form.get("reward_description") or None
        db.session.commit()
        flash("Co-Op Goal updated", "success")
        return redirect(url_for("admin.journey_detail", journey_id=goal.journey_id))
    return render_template("admin/generic_form.html", type_name="Co-Op Goal", item=goal, journey_id=goal.journey_id)


# --- Prize Items ---

@bp.route("/journeys/<int:journey_id>/prizes/new", methods=["GET", "POST"])
@admin_required
def prize_create(journey_id):
    if request.method == "POST":
        prize = PrizeItem(
            journey_id=journey_id,
            name=request.form["name"],
            cost=int(request.form["cost"]),
            image_url=request.form.get("image_url") or None,
        )
        db.session.add(prize)
        db.session.commit()
        flash("Prize created", "success")
        return redirect(url_for("admin.journey_detail", journey_id=journey_id))
    return render_template("admin/generic_form.html", type_name="Prize", item=None, journey_id=journey_id)


@bp.route("/prizes/<int:prize_id>/edit", methods=["GET", "POST"])
@admin_required
def prize_edit(prize_id):
    prize = db.session.get(PrizeItem, prize_id)
    if request.method == "POST":
        prize.name = request.form["name"]
        prize.cost = int(request.form["cost"])
        prize.image_url = request.form.get("image_url") or None
        db.session.commit()
        flash("Prize updated", "success")
        return redirect(url_for("admin.journey_detail", journey_id=prize.journey_id))
    return render_template("admin/generic_form.html", type_name="Prize", item=prize, journey_id=prize.journey_id)


# --- Prize Tiers ---

@bp.route("/journeys/<int:journey_id>/tiers/new", methods=["GET", "POST"])
@admin_required
def tier_create(journey_id):
    if request.method == "POST":
        tier = PrizeTier(
            journey_id=journey_id,
            name=request.form["name"],
            threshold=int(request.form["threshold"]),
            reward_description=request.form.get("reward_description") or None,
        )
        db.session.add(tier)
        db.session.commit()
        flash("Prize Tier created", "success")
        return redirect(url_for("admin.journey_detail", journey_id=journey_id))
    return render_template("admin/generic_form.html", type_name="Prize Tier", item=None, journey_id=journey_id)


@bp.route("/tiers/<int:tier_id>/edit", methods=["GET", "POST"])
@admin_required
def tier_edit(tier_id):
    tier = db.session.get(PrizeTier, tier_id)
    if request.method == "POST":
        tier.name = request.form["name"]
        tier.threshold = int(request.form["threshold"])
        tier.reward_description = request.form.get("reward_description") or None
        db.session.commit()
        flash("Prize Tier updated", "success")
        return redirect(url_for("admin.journey_detail", journey_id=tier.journey_id))
    return render_template("admin/generic_form.html", type_name="Prize Tier", item=tier, journey_id=tier.journey_id)


# --- Side Quests ---

@bp.route("/journeys/<int:journey_id>/side-quests/new", methods=["GET", "POST"])
@admin_required
def side_quest_create(journey_id):
    if request.method == "POST":
        sq = SideQuest(
            journey_id=journey_id,
            name=request.form["name"],
            description=request.form.get("description") or None,
            currency_reward=int(request.form["currency_reward"]),
            repeat_type=request.form.get("repeat_type", "one_time"),
        )
        db.session.add(sq)
        db.session.commit()
        flash("Side Quest created", "success")
        return redirect(url_for("admin.journey_detail", journey_id=journey_id))
    return render_template("admin/generic_form.html", type_name="Side Quest", item=None, journey_id=journey_id)


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
        return redirect(url_for("admin.journey_detail", journey_id=sq.journey_id))
    return render_template("admin/generic_form.html", type_name="Side Quest", item=sq, journey_id=sq.journey_id)


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


# --- Helpers ---

def _parse_date(date_str):
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None
