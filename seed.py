"""Seed script: creates example data for a reading campaign with two themed quests."""
from app import create_app, db
from app.models import (
    Member, Campaign, Quest, ActivityType, EarningRule,
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

        # Campaign (optional grouping for shared goals)
        campaign = Campaign(
            name="Summer 2026 Reading",
            description="Family summer reading challenge",
            status="active",
        )
        db.session.add(campaign)
        db.session.flush()

        # Quests (the core units - linked to campaign)
        quest_a = Quest(
            member_id=kid_a.id,
            campaign_id=campaign.id,
            theme_name="Dungeon Explorer",
            theme_graphic_url=None,
            color_primary="#6366F1",
            color_secondary="#A5B4FC",
            color_background="#1a1525",
            currency_label="Gold",
            progress_label="XP",
            party_goal_label="Raid Boss",
            completion_target=200,
            completion_bonus=25,
        )
        quest_b = Quest(
            member_id=kid_b.id,
            campaign_id=campaign.id,
            theme_name="Forest Ranger",
            theme_graphic_url=None,
            color_primary="#10B981",
            color_secondary="#6EE7B7",
            color_background="#0f1a15",
            currency_label="Gems",
            progress_label="Nature XP",
            party_goal_label="World Event",
            completion_target=150,
            completion_bonus=20,
        )
        db.session.add_all([quest_a, quest_b])
        db.session.flush()

        # Activity Types
        pages_type = ActivityType(
            quest_id=quest_a.id, name="Pages Read", unit_label="pages", sort_order=1
        )
        books_type = ActivityType(
            quest_id=quest_a.id, name="Books Finished", unit_label="books", is_milestone=True, sort_order=2
        )
        minutes_type = ActivityType(
            quest_id=quest_b.id, name="Minutes Read", unit_label="minutes", sort_order=1
        )
        chapters_type = ActivityType(
            quest_id=quest_b.id, name="Chapters Finished", unit_label="chapters", is_milestone=True, sort_order=2
        )
        db.session.add_all([pages_type, books_type, minutes_type, chapters_type])
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
            EarningRule(
                activity_type_id=chapters_type.id,
                rule_type="per_log",
                quantity_required=1,
                currency_reward=15,
            ),
        ])

        # Quest Levels (per quest)
        db.session.add_all([
            QuestLevel(quest_id=quest_a.id, name="Bronze", threshold=100, reward_description="Unlock the treasure shop", sort_order=1),
            QuestLevel(quest_id=quest_a.id, name="Silver", threshold=300, reward_description="Stay up 30 min late", sort_order=2),
            QuestLevel(quest_id=quest_a.id, name="Gold", threshold=600, reward_description="Choose a new book", sort_order=3),
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

        # Shared Campaign Shop Items (available to all quests in the campaign)
        db.session.add_all([
            ShopItem(campaign_id=campaign.id, name="Small Toy", cost=200, sort_order=1),
            ShopItem(campaign_id=campaign.id, name="Family Game Night Pick", cost=150, sort_order=2),
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
            name="The Lost Tome",
            description="Venture into the ancient library to recover the lost spellbook",
            currency_reward=50,
            visibility_mode="checklist_sequential",
            sort_order=1,
        )
        chain_b = SideQuestChain(
            quest_id=quest_b.id,
            name="The Enchanted Trail",
            description="Follow the hidden path through the forest to find the sacred grove",
            currency_reward=40,
            visibility_mode="mystery_sequential",
            sort_order=1,
        )
        db.session.add_all([chain_a, chain_b])
        db.session.flush()

        # Chain steps
        db.session.add_all([
            SideQuest(quest_id=quest_a.id, chain_id=chain_a.id, chain_order=1,
                      name="Enter the Archives", description="Read a non-fiction book about history"),
            SideQuest(quest_id=quest_a.id, chain_id=chain_a.id, chain_order=2,
                      name="Decipher the Runes", description="Read 100 pages in one day"),
            SideQuest(quest_id=quest_a.id, chain_id=chain_a.id, chain_order=3,
                      name="Restore the Tome", description="Write a short book report"),
            SideQuest(quest_id=quest_b.id, chain_id=chain_b.id, chain_order=1,
                      name="Find the Trailhead", description="Read for 30 minutes straight"),
            SideQuest(quest_id=quest_b.id, chain_id=chain_b.id, chain_order=2,
                      name="Cross the Moonlit Bridge", description="Read a new genre"),
            SideQuest(quest_id=quest_b.id, chain_id=chain_b.id, chain_order=3,
                      name="Reach the Sacred Grove", description="Finish a chapter book"),
        ])

        # Party Goals (campaign-level shared goals)
        db.session.add_all([
            PartyGoal(
                campaign_id=campaign.id,
                name="Family Movie Night",
                description="Movie night with popcorn",
                target_amount=500,
                min_individual_contribution=100,
                sort_order=1,
            ),
            PartyGoal(
                campaign_id=campaign.id,
                name="Ice Cream Party",
                description="Ice cream shop visit",
                target_amount=1000,
                min_individual_contribution=300,
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
                description="Log 50 activities across all campaigns",
                icon=None,
                trigger_type="auto",
                trigger_condition={"metric": "total_logs", "threshold": 50},
            ),
        ])

        db.session.commit()
        print("Seed data created successfully.")
        print(f"  Campaign: {campaign.name}")
        print(f"  Quest A: {quest_a.theme_name} ({kid_a.name})")
        print(f"  Quest B: {quest_b.theme_name} ({kid_b.name})")


if __name__ == "__main__":
    seed()
