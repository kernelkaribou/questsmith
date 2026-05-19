"""Seed script: creates example data for a reading journey with two themed quests."""
from app import create_app, db
from app.models import (
    Member, Journey, Quest, ActivityType, EarningRule,
    PartyGoal, QuestLevel, ShopItem, SideQuest, SideQuestChain, Achievement,
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

        # Journey (optional grouping for shared goals)
        journey = Journey(
            name="Summer 2026 Reading",
            description="Family summer reading challenge",
            status="active",
        )
        db.session.add(journey)
        db.session.flush()

        # Quests (the core units - linked to journey)
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

        # Quest Levels (per quest)
        db.session.add_all([
            QuestLevel(quest_id=quest_a.id, name="Bronze", threshold=100, reward_description="Unlock the prize shop", sort_order=1),
            QuestLevel(quest_id=quest_a.id, name="Silver", threshold=300, reward_description="Stay up 30 min late", sort_order=2),
            QuestLevel(quest_id=quest_a.id, name="Gold", threshold=600, reward_description="Pick a new book", sort_order=3),
            QuestLevel(quest_id=quest_b.id, name="Bronze", threshold=100, reward_description="Choose a movie", sort_order=1),
            QuestLevel(quest_id=quest_b.id, name="Silver", threshold=300, reward_description="Sleepover with friend", sort_order=2),
            QuestLevel(quest_id=quest_b.id, name="Gold", threshold=600, reward_description="New craft supplies", sort_order=3),
        ])

        # Shop Items (personal per quest)
        db.session.add_all([
            ShopItem(quest_id=quest_a.id, name="Extra Screen Time (30 min)", cost=50, sort_order=1),
            ShopItem(quest_id=quest_a.id, name="Choose Dinner", cost=100, sort_order=2),
            ShopItem(quest_id=quest_b.id, name="Extra Screen Time (30 min)", cost=50, sort_order=1),
            ShopItem(quest_id=quest_b.id, name="Choose Dinner", cost=100, sort_order=2),
        ])

        # Shared Journey Shop Items (available to all quests in the journey)
        db.session.add_all([
            ShopItem(journey_id=journey.id, name="Small Toy", cost=200, sort_order=1),
            ShopItem(journey_id=journey.id, name="Family Game Night Pick", cost=150, sort_order=2),
        ])

        # Side Quests (per quest)
        db.session.add_all([
            SideQuest(quest_id=quest_a.id, name="Read Outside", description="Read for at least 15 minutes outdoors", currency_reward=15, repeat_type="daily", sort_order=1),
            SideQuest(quest_id=quest_a.id, name="Library Visit", description="Visit the library and check out a book", currency_reward=30, repeat_type="one_time", sort_order=2),
            SideQuest(quest_id=quest_b.id, name="Read to a Sibling", description="Read aloud to a brother or sister", currency_reward=20, repeat_type="daily", sort_order=1),
            SideQuest(quest_id=quest_b.id, name="Library Visit", description="Visit the library and check out a book", currency_reward=30, repeat_type="one_time", sort_order=2),
        ])

        # Side Quest Chains (multi-step quests)
        chain_a = SideQuestChain(
            quest_id=quest_a.id,
            name="The Lost Pokedex",
            description="Help Professor Oak recover the lost Pokedex entries",
            currency_reward=50,
            visibility_mode="checklist_sequential",
            sort_order=1,
        )
        chain_b = SideQuestChain(
            quest_id=quest_b.id,
            name="Spirit Week Challenge",
            description="Complete all Spirit Week activities to earn bonus points",
            currency_reward=40,
            visibility_mode="mystery_sequential",
            sort_order=1,
        )
        db.session.add_all([chain_a, chain_b])
        db.session.flush()

        # Chain steps
        db.session.add_all([
            SideQuest(quest_id=quest_a.id, chain_id=chain_a.id, chain_order=1,
                      name="Talk to Professor Oak", description="Read a non-fiction book about animals"),
            SideQuest(quest_id=quest_a.id, chain_id=chain_a.id, chain_order=2,
                      name="Search the Tall Grass", description="Read 100 pages in one day"),
            SideQuest(quest_id=quest_a.id, chain_id=chain_a.id, chain_order=3,
                      name="Return the Pokedex", description="Write a short book report"),
            SideQuest(quest_id=quest_b.id, chain_id=chain_b.id, chain_order=1,
                      name="Monday: Pep Rally", description="Read for 30 minutes straight"),
            SideQuest(quest_id=quest_b.id, chain_id=chain_b.id, chain_order=2,
                      name="Wednesday: Halftime Show", description="Read a new genre"),
            SideQuest(quest_id=quest_b.id, chain_id=chain_b.id, chain_order=3,
                      name="Friday: Championship", description="Finish a chapter book"),
        ])

        # Party Goals (journey-level shared goals)
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
        ])

        db.session.commit()
        print("Seed data created successfully.")
        print(f"  Journey: {journey.name}")
        print(f"  Quest A: {quest_a.theme_name} ({kid_a.name})")
        print(f"  Quest B: {quest_b.theme_name} ({kid_b.name})")


if __name__ == "__main__":
    seed()
