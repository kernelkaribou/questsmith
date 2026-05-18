from app import db
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Lifetime (Member-level, permanent)
# ---------------------------------------------------------------------------

class Member(db.Model):
    __tablename__ = "members"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    avatar_url = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    quests = db.relationship("Quest", back_populates="member", lazy="dynamic")
    achievement_unlocks = db.relationship("AchievementUnlock", back_populates="member", lazy="dynamic")


class Achievement(db.Model):
    __tablename__ = "achievements"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    icon = db.Column(db.String(500), nullable=True)
    trigger_type = db.Column(db.String(20), nullable=False, default="manual")  # auto, manual
    trigger_condition = db.Column(db.JSON, nullable=True)  # e.g., {"metric": "total_currency", "threshold": 1000}
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    unlocks = db.relationship("AchievementUnlock", back_populates="achievement", lazy="dynamic")


class AchievementUnlock(db.Model):
    __tablename__ = "achievement_unlocks"

    id = db.Column(db.Integer, primary_key=True)
    achievement_id = db.Column(db.Integer, db.ForeignKey("achievements.id"), nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey("members.id"), nullable=False)
    unlocked_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    achievement = db.relationship("Achievement", back_populates="unlocks")
    member = db.relationship("Member", back_populates="achievement_unlocks")

    __table_args__ = (
        db.UniqueConstraint("achievement_id", "member_id", name="uq_achievement_member"),
    )


# ---------------------------------------------------------------------------
# Journey-level (shared campaign)
# ---------------------------------------------------------------------------

class Journey(db.Model):
    __tablename__ = "journeys"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="active")  # active, completed, archived
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    quests = db.relationship("Quest", back_populates="journey", lazy="dynamic")
    coop_goals = db.relationship("CoOpGoal", back_populates="journey", lazy="dynamic")
    prize_tiers = db.relationship("PrizeTier", back_populates="journey", lazy="dynamic")
    prize_items = db.relationship("PrizeItem", back_populates="journey", lazy="dynamic")
    side_quests = db.relationship("SideQuest", back_populates="journey", lazy="dynamic")


class CoOpGoal(db.Model):
    __tablename__ = "coop_goals"

    id = db.Column(db.Integer, primary_key=True)
    journey_id = db.Column(db.Integer, db.ForeignKey("journeys.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    target_amount = db.Column(db.Integer, nullable=False)
    min_individual_contribution = db.Column(db.Integer, nullable=False, default=0)
    reward_description = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    unlocked_at = db.Column(db.DateTime, nullable=True)  # None = locked, set when unlocked
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    journey = db.relationship("Journey", back_populates="coop_goals")


class PrizeTier(db.Model):
    __tablename__ = "prize_tiers"

    id = db.Column(db.Integer, primary_key=True)
    journey_id = db.Column(db.Integer, db.ForeignKey("journeys.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    threshold = db.Column(db.Integer, nullable=False)
    reward_description = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    journey = db.relationship("Journey", back_populates="prize_tiers")


class PrizeItem(db.Model):
    __tablename__ = "prize_items"

    id = db.Column(db.Integer, primary_key=True)
    journey_id = db.Column(db.Integer, db.ForeignKey("journeys.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    cost = db.Column(db.Integer, nullable=False)
    image_url = db.Column(db.String(500), nullable=True)
    is_available = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    journey = db.relationship("Journey", back_populates="prize_items")
    purchases = db.relationship("PrizePurchase", back_populates="prize_item", lazy="dynamic")


class SideQuest(db.Model):
    __tablename__ = "side_quests"

    id = db.Column(db.Integer, primary_key=True)
    journey_id = db.Column(db.Integer, db.ForeignKey("journeys.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    currency_reward = db.Column(db.Integer, nullable=False)
    repeat_type = db.Column(db.String(20), nullable=False, default="one_time")  # one_time, daily, weekly
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    journey = db.relationship("Journey", back_populates="side_quests")
    completions = db.relationship("SideQuestCompletion", back_populates="side_quest", lazy="dynamic")


class SideQuestCompletion(db.Model):
    __tablename__ = "side_quest_completions"

    id = db.Column(db.Integer, primary_key=True)
    side_quest_id = db.Column(db.Integer, db.ForeignKey("side_quests.id"), nullable=False)
    quest_id = db.Column(db.Integer, db.ForeignKey("quests.id"), nullable=False)
    completed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    side_quest = db.relationship("SideQuest", back_populates="completions")
    quest = db.relationship("Quest", back_populates="side_quest_completions")


# ---------------------------------------------------------------------------
# Quest-level (individual within a journey)
# ---------------------------------------------------------------------------

class Quest(db.Model):
    __tablename__ = "quests"

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("members.id"), nullable=False)
    journey_id = db.Column(db.Integer, db.ForeignKey("journeys.id"), nullable=False)

    # Theme configuration
    theme_name = db.Column(db.String(100), nullable=False, default="Adventurer")
    theme_graphic_url = db.Column(db.String(500), nullable=True)  # Primary quest graphic/image
    color_primary = db.Column(db.String(7), nullable=False, default="#4F46E5")  # Hex color
    color_secondary = db.Column(db.String(7), nullable=False, default="#818CF8")  # Hex color

    # Label overrides (null = use defaults: Gold, XP, Co-Op Goal)
    currency_label = db.Column(db.String(50), nullable=True)
    progress_label = db.Column(db.String(50), nullable=True)
    coop_label = db.Column(db.String(50), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    member = db.relationship("Member", back_populates="quests")
    journey = db.relationship("Journey", back_populates="quests")
    activity_types = db.relationship("ActivityType", back_populates="quest", lazy="dynamic")
    transactions = db.relationship("Transaction", back_populates="quest", lazy="dynamic")
    activity_logs = db.relationship("ActivityLog", back_populates="quest", lazy="dynamic")
    side_quest_completions = db.relationship("SideQuestCompletion", back_populates="quest", lazy="dynamic")
    prize_purchases = db.relationship("PrizePurchase", back_populates="quest", lazy="dynamic")

    __table_args__ = (
        db.UniqueConstraint("member_id", "journey_id", name="uq_member_journey"),
    )

    @property
    def display_currency(self):
        return self.currency_label or "Gold"

    @property
    def display_progress(self):
        return self.progress_label or "XP"

    @property
    def display_coop(self):
        return self.coop_label or "Co-Op Goal"


class ActivityType(db.Model):
    __tablename__ = "activity_types"

    id = db.Column(db.Integer, primary_key=True)
    quest_id = db.Column(db.Integer, db.ForeignKey("quests.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)  # e.g., "Pages Read"
    unit_label = db.Column(db.String(50), nullable=False)  # e.g., "pages"
    icon = db.Column(db.String(500), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    quest = db.relationship("Quest", back_populates="activity_types")
    earning_rules = db.relationship("EarningRule", back_populates="activity_type", lazy="dynamic")
    activity_logs = db.relationship("ActivityLog", back_populates="activity_type", lazy="dynamic")


class EarningRule(db.Model):
    __tablename__ = "earning_rules"

    id = db.Column(db.Integer, primary_key=True)
    activity_type_id = db.Column(db.Integer, db.ForeignKey("activity_types.id"), nullable=False)
    rule_type = db.Column(db.String(20), nullable=False, default="per_batch")  # per_batch, per_log
    quantity_required = db.Column(db.Integer, nullable=False)  # e.g., 50 (pages)
    currency_reward = db.Column(db.Integer, nullable=False)  # e.g., 10 (currency units)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    activity_type = db.relationship("ActivityType", back_populates="earning_rules")

    # per_batch: for every quantity_required units logged, award currency_reward
    #   e.g., per_batch with quantity_required=50, currency_reward=10
    #   means "for every 50 pages, earn 10 currency"
    # per_log: each activity log entry that meets quantity_required threshold awards currency_reward
    #   e.g., per_log with quantity_required=1, currency_reward=5
    #   means "each time you log any amount, earn 5 currency"


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    quest_id = db.Column(db.Integer, db.ForeignKey("quests.id"), nullable=False)
    activity_type_id = db.Column(db.Integer, db.ForeignKey("activity_types.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text, nullable=True)
    logged_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    quest = db.relationship("Quest", back_populates="activity_logs")
    activity_type = db.relationship("ActivityType", back_populates="activity_logs")
    transactions = db.relationship("Transaction", back_populates="activity_log", lazy="dynamic")


class Transaction(db.Model):
    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    quest_id = db.Column(db.Integer, db.ForeignKey("quests.id"), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # earn, spend, side_quest_reward, adjustment
    amount = db.Column(db.Integer, nullable=False)  # Always positive; type determines direction
    description = db.Column(db.Text, nullable=True)
    activity_log_id = db.Column(db.Integer, db.ForeignKey("activity_logs.id"), nullable=True)
    earning_rule_id = db.Column(db.Integer, db.ForeignKey("earning_rules.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    quest = db.relationship("Quest", back_populates="transactions")
    activity_log = db.relationship("ActivityLog", back_populates="transactions")

    __table_args__ = (
        db.UniqueConstraint("activity_log_id", "earning_rule_id", name="uq_log_rule"),
    )


class PrizePurchase(db.Model):
    __tablename__ = "prize_purchases"

    id = db.Column(db.Integer, primary_key=True)
    prize_item_id = db.Column(db.Integer, db.ForeignKey("prize_items.id"), nullable=False)
    quest_id = db.Column(db.Integer, db.ForeignKey("quests.id"), nullable=False)
    transaction_id = db.Column(db.Integer, db.ForeignKey("transactions.id"), nullable=False)
    purchased_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    prize_item = db.relationship("PrizeItem", back_populates="purchases")
    quest = db.relationship("Quest", back_populates="prize_purchases")
