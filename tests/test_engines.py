"""Tests for core engines."""
import pytest
from datetime import datetime, timezone, timedelta

from app import create_app, db
from app.models import (
    Member, Journey, Quest, ActivityType, EarningRule,
    PartyGoal, QuestLevel, ShopItem, SideQuest, SideQuestChain, Achievement,
)
from tests.conftest import TestConfig


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        yield app


@pytest.fixture
def seeded(app):
    """Create test data: one journey, two members, two quests."""
    with app.app_context():
        member_a = Member(name="Alex")
        member_b = Member(name="Jordan")
        db.session.add_all([member_a, member_b])
        db.session.flush()

        journey = Journey(name="Summer Reading", status="active")
        db.session.add(journey)
        db.session.flush()

        quest_a = Quest(
            member_id=member_a.id, journey_id=journey.id,
            theme_name="Pokemon", currency_label="Pokeballs",
            color_primary="#FF0000", color_secondary="#FF9999",
        )
        quest_b = Quest(
            member_id=member_b.id, journey_id=journey.id,
            theme_name="Cheer", currency_label="Spirit Points",
            color_primary="#FF00FF", color_secondary="#FF99FF",
        )
        db.session.add_all([quest_a, quest_b])
        db.session.flush()

        pages = ActivityType(quest_id=quest_a.id, name="Pages Read", unit_label="pages")
        minutes = ActivityType(quest_id=quest_b.id, name="Minutes Read", unit_label="minutes")
        db.session.add_all([pages, minutes])
        db.session.flush()

        rule_a = EarningRule(activity_type_id=pages.id, rule_type="per_batch", quantity_required=50, currency_reward=10)
        rule_b = EarningRule(activity_type_id=minutes.id, rule_type="per_batch", quantity_required=30, currency_reward=10)
        db.session.add_all([rule_a, rule_b])
        db.session.commit()

        # Return IDs so tests can re-query within their own session context
        return {
            "member_a_id": member_a.id, "member_b_id": member_b.id,
            "journey_id": journey.id,
            "quest_a_id": quest_a.id, "quest_b_id": quest_b.id,
            "pages_id": pages.id, "minutes_id": minutes.id,
            "rule_a_id": rule_a.id, "rule_b_id": rule_b.id,
        }


class TestLedgerEngine:
    def test_balance_starts_at_zero(self, app, seeded):
        from app.engines.ledger import get_balance
        with app.app_context():
            assert get_balance(seeded["quest_a_id"]) == 0

    def test_earn_increases_balance(self, app, seeded):
        from app.engines.ledger import get_balance, record_earn
        with app.app_context():
            record_earn(seeded["quest_a_id"], 50, "test earn")
            db.session.commit()
            assert get_balance(seeded["quest_a_id"]) == 50

    def test_spend_decreases_balance(self, app, seeded):
        from app.engines.ledger import get_balance, record_earn, record_spend
        with app.app_context():
            record_earn(seeded["quest_a_id"], 50, "earn")
            db.session.commit()
            record_spend(seeded["quest_a_id"], 20, "spend")
            db.session.commit()
            assert get_balance(seeded["quest_a_id"]) == 30

    def test_spend_fails_if_insufficient(self, app, seeded):
        from app.engines.ledger import record_earn, record_spend
        with app.app_context():
            record_earn(seeded["quest_a_id"], 10, "earn")
            db.session.commit()
            result = record_spend(seeded["quest_a_id"], 20, "overspend")
            assert result is None

    def test_journey_totals(self, app, seeded):
        from app.engines.ledger import record_earn, get_journey_totals
        with app.app_context():
            record_earn(seeded["quest_a_id"], 100, "earn a")
            record_earn(seeded["quest_b_id"], 75, "earn b")
            db.session.commit()
            totals = get_journey_totals(seeded["journey_id"])
            assert totals[seeded["member_a_id"]] == 100
            assert totals[seeded["member_b_id"]] == 75


class TestQuestEngine:
    def test_log_activity_per_batch(self, app, seeded):
        from app.engines.quest import log_activity
        from app.engines.ledger import get_balance
        with app.app_context():
            log, txns = log_activity(seeded["quest_a_id"], seeded["pages_id"], 120)
            db.session.commit()
            assert log is not None
            assert len(txns) == 1
            # 120 pages // 50 = 2 batches * 10 = 20 currency
            assert get_balance(seeded["quest_a_id"]) == 20

    def test_log_activity_remainder_no_reward(self, app, seeded):
        from app.engines.quest import log_activity
        from app.engines.ledger import get_balance
        with app.app_context():
            log, txns = log_activity(seeded["quest_a_id"], seeded["pages_id"], 30)
            db.session.commit()
            # 30 pages < 50 required, no reward
            assert len(txns) == 0
            assert get_balance(seeded["quest_a_id"]) == 0

    def test_log_activity_cumulative_carry_forward(self, app, seeded):
        from app.engines.quest import log_activity, get_earning_progress
        from app.engines.ledger import get_balance
        with app.app_context():
            # Log 40 pages (below 50 threshold)
            log, txns = log_activity(seeded["quest_a_id"], seeded["pages_id"], 40)
            db.session.commit()
            assert len(txns) == 0
            assert get_balance(seeded["quest_a_id"]) == 0

            # Log 30 more (cumulative 70: 1 batch of 50, remainder 20)
            log, txns = log_activity(seeded["quest_a_id"], seeded["pages_id"], 30)
            db.session.commit()
            assert len(txns) == 1
            assert get_balance(seeded["quest_a_id"]) == 10

            # Check progress: remainder should be 20, need 30 more for next
            progress = get_earning_progress(seeded["quest_a_id"])
            pages_progress = [p for p in progress if p["activity_type"].name == "Pages Read"][0]
            assert pages_progress["remainder"] == 20
            assert pages_progress["units_to_next"] == 30

    def test_wrong_activity_type_rejected(self, app, seeded):
        from app.engines.quest import log_activity
        with app.app_context():
            # Try to log minutes type on quest_a (pages quest)
            log, txns = log_activity(seeded["quest_a_id"], seeded["minutes_id"], 60)
            assert log is None

    def test_quest_context_labels(self, app, seeded):
        from app.engines.quest import get_quest_context
        with app.app_context():
            ctx = get_quest_context(seeded["quest_a_id"])
            assert ctx["currency_label"] == "Pokeballs"
            assert ctx["colors"]["primary"] == "#FF0000"


class TestValidationEngine:
    def test_party_goal_locked_initially(self, app, seeded):
        from app.engines.validation import check_party_goal
        with app.app_context():
            goal = PartyGoal(
                journey_id=seeded["journey_id"], name="Movie Night",
                target_amount=100, min_individual_contribution=30,
            )
            db.session.add(goal)
            db.session.commit()

            result = check_party_goal(goal)
            assert result["unlocked"] is False
            assert result["volume_met"] is False

    def test_party_goal_unlocks_when_met(self, app, seeded):
        from app.engines.validation import check_party_goal
        from app.engines.ledger import record_earn
        with app.app_context():
            goal = PartyGoal(
                journey_id=seeded["journey_id"], name="Movie Night",
                target_amount=100, min_individual_contribution=30,
            )
            db.session.add(goal)
            record_earn(seeded["quest_a_id"], 60, "earn a")
            record_earn(seeded["quest_b_id"], 50, "earn b")
            db.session.commit()

            result = check_party_goal(goal)
            assert result["unlocked"] is True
            assert result["volume_met"] is True
            assert result["all_fair"] is True

    def test_party_goal_fairness_blocks(self, app, seeded):
        from app.engines.validation import check_party_goal
        from app.engines.ledger import record_earn
        with app.app_context():
            goal = PartyGoal(
                journey_id=seeded["journey_id"], name="Movie Night",
                target_amount=100, min_individual_contribution=40,
            )
            db.session.add(goal)
            # A earns 90, B earns 20 — total met but B below minimum
            record_earn(seeded["quest_a_id"], 90, "earn a")
            record_earn(seeded["quest_b_id"], 20, "earn b")
            db.session.commit()

            result = check_party_goal(goal)
            assert result["unlocked"] is False
            assert result["volume_met"] is True
            assert result["all_fair"] is False

    def test_quest_level_unlocks(self, app, seeded):
        from app.engines.validation import get_unlocked_levels
        from app.engines.ledger import record_earn
        with app.app_context():
            QuestLevel.query.delete()
            db.session.add_all([
                QuestLevel(quest_id=seeded["quest_a_id"], name="Bronze", threshold=50, sort_order=1),
                QuestLevel(quest_id=seeded["quest_a_id"], name="Silver", threshold=150, sort_order=2),
            ])
            record_earn(seeded["quest_a_id"], 100, "earn")
            db.session.commit()

            levels = get_unlocked_levels(seeded["quest_a_id"])
            assert levels[0]["unlocked"] is True  # Bronze (100 >= 50)
            assert levels[1]["unlocked"] is False  # Silver (100 < 150)


class TestSideQuestEngine:
    def test_complete_one_time(self, app, seeded):
        from app.engines.side_quest import complete_side_quest, get_available_side_quests
        from app.engines.ledger import get_balance
        with app.app_context():
            sq = SideQuest(
                quest_id=seeded["quest_a_id"], name="Library Visit",
                currency_reward=30, repeat_type="one_time",
            )
            db.session.add(sq)
            db.session.commit()

            result = complete_side_quest(sq.id, seeded["quest_a_id"])
            db.session.commit()
            assert result is not None
            assert get_balance(seeded["quest_a_id"]) == 30

            # Can't complete again
            result2 = complete_side_quest(sq.id, seeded["quest_a_id"])
            assert result2 is None

    def test_daily_cooldown(self, app, seeded):
        from app.engines.side_quest import get_available_side_quests, complete_side_quest
        with app.app_context():
            sq = SideQuest(
                quest_id=seeded["quest_a_id"], name="Read Outside",
                currency_reward=15, repeat_type="daily",
            )
            db.session.add(sq)
            db.session.commit()

            # First completion works
            result = complete_side_quest(sq.id, seeded["quest_a_id"])
            db.session.commit()
            assert result is not None

            # Same day blocked
            available = get_available_side_quests(seeded["quest_a_id"])
            assert available[0]["can_complete"] is False

    def test_chain_sequential_completion(self, app, seeded):
        from app.engines.side_quest import get_available_chains, complete_chain_step
        from app.engines.ledger import get_balance
        with app.app_context():
            chain = SideQuestChain(
                quest_id=seeded["quest_a_id"], name="Test Chain",
                currency_reward=50, visibility_mode="checklist_sequential",
            )
            db.session.add(chain)
            db.session.flush()

            step1 = SideQuest(quest_id=seeded["quest_a_id"], chain_id=chain.id, chain_order=1, name="Step 1")
            step2 = SideQuest(quest_id=seeded["quest_a_id"], chain_id=chain.id, chain_order=2, name="Step 2")
            step3 = SideQuest(quest_id=seeded["quest_a_id"], chain_id=chain.id, chain_order=3, name="Step 3")
            db.session.add_all([step1, step2, step3])
            db.session.commit()

            # Can't skip to step 2
            result = complete_chain_step(step2.id, seeded["quest_a_id"])
            assert result is None

            # Complete step 1
            result = complete_chain_step(step1.id, seeded["quest_a_id"])
            db.session.commit()
            assert result is not None
            assert result["chain_completed"] is False
            assert get_balance(seeded["quest_a_id"]) == 0

            # Complete step 2
            result = complete_chain_step(step2.id, seeded["quest_a_id"])
            db.session.commit()
            assert result["chain_completed"] is False

            # Complete step 3 -> chain complete, reward awarded
            result = complete_chain_step(step3.id, seeded["quest_a_id"])
            db.session.commit()
            assert result["chain_completed"] is True
            assert get_balance(seeded["quest_a_id"]) == 50

    def test_chain_any_order(self, app, seeded):
        from app.engines.side_quest import complete_chain_step
        from app.engines.ledger import get_balance
        with app.app_context():
            chain = SideQuestChain(
                quest_id=seeded["quest_a_id"], name="Any Order Chain",
                currency_reward=30, visibility_mode="checklist_any_order",
            )
            db.session.add(chain)
            db.session.flush()

            step1 = SideQuest(quest_id=seeded["quest_a_id"], chain_id=chain.id, chain_order=1, name="A")
            step2 = SideQuest(quest_id=seeded["quest_a_id"], chain_id=chain.id, chain_order=2, name="B")
            db.session.add_all([step1, step2])
            db.session.commit()

            # Can complete step 2 first (any order)
            result = complete_chain_step(step2.id, seeded["quest_a_id"])
            db.session.commit()
            assert result is not None
            assert result["chain_completed"] is False

            # Complete step 1 -> chain done
            result = complete_chain_step(step1.id, seeded["quest_a_id"])
            db.session.commit()
            assert result["chain_completed"] is True
            assert get_balance(seeded["quest_a_id"]) == 30

    def test_chain_steps_excluded_from_standalone(self, app, seeded):
        from app.engines.side_quest import get_available_side_quests
        with app.app_context():
            chain = SideQuestChain(
                quest_id=seeded["quest_a_id"], name="Hidden Chain",
                currency_reward=10, visibility_mode="checklist_sequential",
            )
            db.session.add(chain)
            db.session.flush()

            standalone = SideQuest(quest_id=seeded["quest_a_id"], name="Visible", currency_reward=5, repeat_type="one_time")
            chained = SideQuest(quest_id=seeded["quest_a_id"], chain_id=chain.id, chain_order=1, name="Hidden Step")
            db.session.add_all([standalone, chained])
            db.session.commit()

            available = get_available_side_quests(seeded["quest_a_id"])
            names = [item["side_quest"].name for item in available]
            assert "Visible" in names
            assert "Hidden Step" not in names


class TestAchievementEngine:
    def test_auto_achievement_unlocks(self, app, seeded):
        from app.engines.achievement import check_achievements
        from app.engines.quest import log_activity
        with app.app_context():
            ach = Achievement(
                name="First Steps", trigger_type="auto",
                trigger_condition={"metric": "total_logs", "threshold": 1},
            )
            db.session.add(ach)
            db.session.commit()

            log_activity(seeded["quest_a_id"], seeded["pages_id"], 50)
            db.session.commit()

            new_unlocks = check_achievements(seeded["member_a_id"])
            db.session.commit()
            assert len(new_unlocks) == 1
            assert new_unlocks[0].name == "First Steps"

    def test_manual_award(self, app, seeded):
        from app.engines.achievement import manually_award, get_member_achievements
        with app.app_context():
            ach = Achievement(name="Star Reader", trigger_type="manual")
            db.session.add(ach)
            db.session.commit()

            unlock = manually_award(ach.id, seeded["member_a_id"])
            db.session.commit()
            assert unlock is not None

            # Can't award twice
            assert manually_award(ach.id, seeded["member_a_id"]) is None

            achievements = get_member_achievements(seeded["member_a_id"])
            assert achievements[0]["unlocked"] is True


class TestInputValidation:
    def test_negative_quantity_rejected(self, app, seeded):
        from app.engines.quest import log_activity
        with app.app_context():
            log, txns = log_activity(seeded["quest_a_id"], seeded["pages_id"], -5)
            assert log is None
            assert txns == []

    def test_zero_quantity_rejected(self, app, seeded):
        from app.engines.quest import log_activity
        with app.app_context():
            log, txns = log_activity(seeded["quest_a_id"], seeded["pages_id"], 0)
            assert log is None
            assert txns == []

    def test_negative_earn_raises(self, app, seeded):
        from app.engines.ledger import record_earn
        with app.app_context():
            with pytest.raises(ValueError):
                record_earn(seeded["quest_a_id"], -10, "bad earn")

    def test_negative_spend_raises(self, app, seeded):
        from app.engines.ledger import record_earn, record_spend
        with app.app_context():
            record_earn(seeded["quest_a_id"], 100, "seed")
            db.session.commit()
            with pytest.raises(ValueError):
                record_spend(seeded["quest_a_id"], -5, "bad spend")


class TestPartyGoalFairnessFixed:
    def test_zero_contribution_member_with_zero_minimum(self, app, seeded):
        """When min_individual_contribution=0, zero-contribution members should NOT block."""
        from app.engines.validation import check_party_goal
        from app.engines.ledger import record_earn
        with app.app_context():
            goal = PartyGoal(
                journey_id=seeded["journey_id"], name="Easy Goal",
                target_amount=50, min_individual_contribution=0,
            )
            db.session.add(goal)
            # Only member A earns, member B has zero
            record_earn(seeded["quest_a_id"], 60, "earn")
            db.session.commit()

            result = check_party_goal(goal)
            assert result["volume_met"] is True
            assert result["all_fair"] is True
            assert result["unlocked"] is True


class TestEarningRuleEditSafety:
    def test_rule_reward_change_does_not_break_batch_calc(self, app, seeded):
        """Changing currency_reward shouldn't reinterpret historical transactions."""
        from app.engines.quest import log_activity
        from app.engines.ledger import get_balance
        with app.app_context():
            # Log 100 pages: 2 batches * 10 = 20 earned
            log, txns = log_activity(seeded["quest_a_id"], seeded["pages_id"], 100)
            db.session.commit()
            assert get_balance(seeded["quest_a_id"]) == 20

            # Admin changes reward from 10 to 5 (now batches give 5 instead of 10)
            rule = db.session.get(EarningRule, seeded["rule_a_id"])
            rule.currency_reward = 5
            db.session.commit()

            # Log 50 more pages: cumulative 150 = 3 batches total, 2 already paid
            log, txns = log_activity(seeded["quest_a_id"], seeded["pages_id"], 50)
            db.session.commit()
            # Should earn 1 new batch * 5 (new reward) = 5
            assert get_balance(seeded["quest_a_id"]) == 25


class TestQuestCompletion:
    def test_quest_completes_at_target(self, app, seeded):
        from app.engines.quest import log_activity
        from app.engines.ledger import get_balance
        with app.app_context():
            quest = db.session.get(Quest, seeded["quest_a_id"])
            quest.completion_target = 20
            quest.completion_bonus = 5
            db.session.commit()

            # Log 100 pages = 2 batches * 10 = 20 earned, hits target
            log, txns = log_activity(seeded["quest_a_id"], seeded["pages_id"], 100)
            db.session.commit()

            quest = db.session.get(Quest, seeded["quest_a_id"])
            assert quest.completed_at is not None
            # Balance = 20 (earning) + 5 (completion bonus) = 25
            assert get_balance(seeded["quest_a_id"]) == 25

    def test_quest_no_double_completion(self, app, seeded):
        from app.engines.quest import log_activity
        from app.engines.ledger import get_balance
        with app.app_context():
            quest = db.session.get(Quest, seeded["quest_a_id"])
            quest.completion_target = 10
            quest.completion_bonus = 5
            db.session.commit()

            log_activity(seeded["quest_a_id"], seeded["pages_id"], 50)
            db.session.commit()

            # Log again - should NOT get second completion bonus
            log_activity(seeded["quest_a_id"], seeded["pages_id"], 50)
            db.session.commit()

            # 50 pages = 1 batch * 10 = 10 + 5 bonus (first log)
            # 100 total = 2 batches * 10 = 20 (cumulative) + 5 bonus
            assert get_balance(seeded["quest_a_id"]) == 25


class TestLevelUnlockPersistence:
    def test_level_unlocks_persisted(self, app, seeded):
        from app.engines.validation import check_level_unlocks, get_unlocked_levels
        from app.engines.ledger import record_earn
        from app.models import QuestLevelUnlock
        with app.app_context():
            QuestLevel.query.delete()
            db.session.add_all([
                QuestLevel(quest_id=seeded["quest_a_id"], name="Bronze", threshold=50, sort_order=1),
                QuestLevel(quest_id=seeded["quest_a_id"], name="Silver", threshold=150, sort_order=2),
            ])
            record_earn(seeded["quest_a_id"], 100, "earn")
            db.session.commit()

            new_unlocks = check_level_unlocks(seeded["quest_a_id"])
            db.session.commit()

            # Bronze should be newly unlocked (100 >= 50)
            assert len(new_unlocks) == 1
            assert new_unlocks[0].quest_level.name == "Bronze"

            # Persisted in DB
            persisted = QuestLevelUnlock.query.filter_by(quest_id=seeded["quest_a_id"]).all()
            assert len(persisted) == 1

            # Running again doesn't create duplicates
            more = check_level_unlocks(seeded["quest_a_id"])
            db.session.commit()
            assert len(more) == 0

    def test_unlocked_levels_includes_timestamp(self, app, seeded):
        from app.engines.validation import check_level_unlocks, get_unlocked_levels
        from app.engines.ledger import record_earn
        with app.app_context():
            QuestLevel.query.delete()
            db.session.add_all([
                QuestLevel(quest_id=seeded["quest_a_id"], name="Bronze", threshold=50, sort_order=1),
            ])
            record_earn(seeded["quest_a_id"], 100, "earn")
            db.session.commit()

            check_level_unlocks(seeded["quest_a_id"])
            db.session.commit()

            levels = get_unlocked_levels(seeded["quest_a_id"])
            assert levels[0]["unlocked"] is True
            assert levels[0]["unlocked_at"] is not None
