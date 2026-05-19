"""Seed script: creates example data for a reading journey with two themed quests."""
from app import create_app, db
from app.models import (
    Member, Journey, Quest, ActivityType, EarningRule,
    PartyGoal, QuestLevel, ShopItem, SideQuest, Achievement,
)


def seed():
    app = create_app()
    with app.app_context():
        if Member.query.first():
            print("Database already has data. Skipping seed.")
            return

        # Members
        kid_a = Member(name="Alex", avatar_url=None)
        kid_b = Member(name="Jordan", avatar_url=None)
        db.session.add_all([kid_a, kid_b])
        db.session.flush()

        # Journey
        journey = Journey(
            name="Summer 2026 Reading",
            description="Family summer reading challenge",
            status="active",
        )
        db.session.add(journey)
        db.session.flush()

        # Quests
        quest_a = Quest(
            member_id=kid_a.id,
            journey_id=journey.id,
            theme_name="Pokemon Trainer",
            theme_graphic_url=None,
            color_primary="#EF4444",
            color_secondary="#FCA5A5",
            currency_label="Pokeballs",
            progress_label="Trainer XP",
            party_goal_label="Gym Battle",
        )
        quest_b = Quest(
            member_id=kid_b.id,
            journey_id=journey.id,
            theme_name="Cheer Camp",
            theme_graphic_url=None,
            color_primary="#EC4899",
            color_secondary="#F9A8D4",
            currency_label="Spirit Points",
            progress_label="Cheer Energy",
            party_goal_label="Team Rally",
        )
        db.session.add_all([quest_a, quest_b])
        db.session.flush()

        # Activity Types
        pages_type = ActivityType(
            quest_id=quest_a.id, name="Pages Read", unit_label="pages", sort_order=1
        )
        books_type = ActivityType(
            quest_id=quest_a.id, name="Books Finished", unit_label="books", sort_order=2
        )
        minutes_type = ActivityType(
            quest_id=quest_b.id, name="Minutes Read", unit_label="minutes", sort_order=1
        )
        db.session.add_all([pages_type, books_type, minutes_type])
        db.session.flush()

        # Earning Rules
        db.session.add_all([
            EarningRule(
                activity_type_id=pages_type.id,
                rule_type="per_batch",
                quantity_required=50,
                currency_reward=10,
            ),
            EarningRule(
                activity_type_id=books_type.id,
                rule_type="per_log",
                quantity_required=1,
                currency_reward=25,
            ),
            EarningRule(
                activity_type_id=minutes_type.id,
                rule_type="per_batch",
                quantity_required=30,
                currency_reward=10,
            ),
        ])

        # Party Goals
        db.session.add_all([
            PartyGoal(
                journey_id=journey.id,
                name="Family Movie Night",
                description="Earn 500 combined currency to unlock a family movie trip",
                target_amount=500,
                min_individual_contribution=100,
                reward_description="Movie night with popcorn",
                sort_order=1,
            ),
            PartyGoal(
                journey_id=journey.id,
                name="Ice Cream Party",
                description="Earn 1000 combined currency for an ice cream outing",
                target_amount=1000,
                min_individual_contribution=300,
                reward_description="Ice cream shop visit",
                sort_order=2,
            ),
        ])

        # Quest Levels
        db.session.add_all([
            QuestLevel(journey_id=journey.id, name="Bronze", threshold=100, reward_description="Unlock the prize shop", sort_order=1),
            QuestLevel(journey_id=journey.id, name="Silver", threshold=300, reward_description="Stay up 30 min late", sort_order=2),
            QuestLevel(journey_id=journey.id, name="Gold", threshold=600, reward_description="Pick a new book", sort_order=3),
        ])

        # Shop Items
        db.session.add_all([
            ShopItem(journey_id=journey.id, name="Extra Screen Time (30 min)", cost=50, sort_order=1),
            ShopItem(journey_id=journey.id, name="Choose Dinner", cost=100, sort_order=2),
            ShopItem(journey_id=journey.id, name="Small Toy", cost=200, sort_order=3),
        ])

        # Side Quests
        db.session.add_all([
            SideQuest(
                journey_id=journey.id,
                name="Read Outside",
                description="Read for at least 15 minutes outdoors",
                currency_reward=15,
                repeat_type="daily",
                sort_order=1,
            ),
            SideQuest(
                journey_id=journey.id,
                name="Read to a Sibling",
                description="Read aloud to a brother or sister",
                currency_reward=20,
                repeat_type="daily",
                sort_order=2,
            ),
            SideQuest(
                journey_id=journey.id,
                name="Library Visit",
                description="Visit the library and check out a book",
                currency_reward=30,
                repeat_type="one_time",
                sort_order=3,
            ),
        ])

        # Achievements (lifetime)
        db.session.add_all([
            Achievement(
                name="First Steps",
                description="Log your first activity",
                icon=None,
                trigger_type="auto",
                trigger_condition={"metric": "total_logs", "threshold": 1},
            ),
            Achievement(
                name="Bookworm",
                description="Log 50 activities across all journeys",
                icon=None,
                trigger_type="auto",
                trigger_condition={"metric": "total_logs", "threshold": 50},
            ),
            Achievement(
                name="Journey Complete",
                description="Finish your first journey",
                icon=None,
                trigger_type="auto",
                trigger_condition={"metric": "journeys_completed", "threshold": 1},
            ),
        ])

        db.session.commit()
        print("Seed data created successfully.")
        print(f"  Journey: {journey.name}")
        print(f"  Quest A: {quest_a.theme_name} ({kid_a.name})")
        print(f"  Quest B: {quest_b.theme_name} ({kid_b.name})")


if __name__ == "__main__":
    seed()
