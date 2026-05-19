import pytest
from app import create_app, db
from app.models import Member, Journey, Quest, ActivityType, EarningRule, PartyGoal, ShopItem, SideQuest, SideQuestChain
from tests.conftest import TestConfig


@pytest.fixture
def app():
    application = create_app(TestConfig)
    with application.app_context():
        yield application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(client):
    """Client already logged in as admin."""
    client.post("/admin/login", data={"pin": "1234"})
    return client


@pytest.fixture
def seeded(app):
    """Seed a full journey with member, quest, activity type, earning rule."""
    m = Member(name="Test Kid")
    db.session.add(m)
    j = Journey(name="Summer Reading", status="active")
    db.session.add(j)
    db.session.flush()
    q = Quest(member_id=m.id, journey_id=j.id, theme_name="Pokemon", color_primary="#FF0000", color_secondary="#FFAA00")
    db.session.add(q)
    db.session.flush()
    at = ActivityType(quest_id=q.id, name="Pages", unit_label="pages")
    db.session.add(at)
    db.session.flush()
    rule = EarningRule(activity_type_id=at.id, rule_type="per_batch", quantity_required=50, currency_reward=10)
    db.session.add(rule)
    goal = PartyGoal(journey_id=j.id, name="Movie Night", target_amount=100, min_individual_contribution=0)
    db.session.add(goal)
    prize = ShopItem(quest_id=q.id, name="Ice Cream", cost=20)
    db.session.add(prize)
    sq = SideQuest(quest_id=q.id, name="Read Outside", currency_reward=5, repeat_type="daily")
    db.session.add(sq)
    db.session.commit()
    return {"member_id": m.id, "journey_id": j.id, "quest_id": q.id, "activity_type_id": at.id, "prize_id": prize.id}


# --- Dashboard Tests ---

def test_dashboard_index(client):
    response = client.get("/")
    assert response.status_code == 200


def test_dashboard_member_select_redirect(client, seeded):
    response = client.get(f"/member/{seeded['member_id']}")
    assert response.status_code == 302


def test_dashboard_quest_view(client, seeded):
    response = client.get(f"/quest/{seeded['quest_id']}")
    assert response.status_code == 200
    assert b"Pokemon" in response.data


def test_dashboard_profile(client, seeded):
    response = client.get(f"/member/{seeded['member_id']}/profile")
    assert response.status_code == 200
    assert b"Lifetime" in response.data


def test_dashboard_history(client, seeded):
    response = client.get(f"/quest/{seeded['quest_id']}/history")
    assert response.status_code == 200


# --- Admin Auth Tests ---

def test_admin_redirects_without_auth(client):
    response = client.get("/admin/")
    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]


def test_admin_login_wrong_pin(client):
    response = client.post("/admin/login", data={"pin": "0000"}, follow_redirects=True)
    assert b"Incorrect" in response.data


def test_admin_login_and_index(auth_client, seeded):
    response = auth_client.get("/admin/")
    assert response.status_code == 200
    assert b"Summer Reading" in response.data


def test_admin_logout(auth_client):
    response = auth_client.get("/admin/logout", follow_redirects=True)
    assert b"Choose Your Adventurer" in response.data


# --- Admin CRUD Tests ---

def test_admin_create_member(auth_client):
    r = auth_client.post("/admin/members/new", data={"name": "New Kid"}, follow_redirects=True)
    assert r.status_code == 200
    assert b"New Kid" in r.data


def test_admin_create_journey(auth_client):
    r = auth_client.post("/admin/journeys/new", data={"name": "Fall Quest", "status": "active"}, follow_redirects=True)
    assert r.status_code == 200
    assert b"Fall Quest" in r.data


def test_admin_journey_detail(auth_client, seeded):
    r = auth_client.get(f"/admin/journeys/{seeded['journey_id']}")
    assert r.status_code == 200
    assert b"Summer Reading" in r.data


def test_admin_create_quest(auth_client, seeded, app):
    # Need a different member
    with app.app_context():
        m2 = Member(name="Second Kid")
        db.session.add(m2)
        db.session.commit()
        member_id = m2.id
    r = auth_client.post("/admin/quests/new", data={
        "member_id": member_id,
        "journey_id": seeded["journey_id"],
        "theme_name": "Cheer Camp",
        "color_primary": "#00FF00",
        "color_secondary": "#88FF88",
    }, follow_redirects=True)
    assert r.status_code == 200
    assert b"Cheer Camp" in r.data


def test_admin_log_activity(auth_client, seeded):
    r = auth_client.post("/admin/log", data={
        "quest_id": seeded["quest_id"],
        "activity_type_id": seeded["activity_type_id"],
        "quantity": "100",
    }, follow_redirects=True)
    assert r.status_code == 200
    assert b"earned 20" in r.data


def test_admin_redeem_prize(auth_client, seeded):
    # First earn some currency
    auth_client.post("/admin/log", data={
        "quest_id": seeded["quest_id"],
        "activity_type_id": seeded["activity_type_id"],
        "quantity": "150",
    })
    r = auth_client.post(f"/admin/quests/{seeded['quest_id']}/redeem", data={
        "item_id": seeded["prize_id"],
    }, follow_redirects=True)
    assert r.status_code == 200
    assert b"redeemed" in r.data


def test_admin_redeem_insufficient_balance(auth_client, seeded):
    r = auth_client.post(f"/admin/quests/{seeded['quest_id']}/redeem", data={
        "item_id": seeded["prize_id"],
    }, follow_redirects=True)
    assert b"Insufficient" in r.data


def test_admin_party_goal_crud(auth_client, seeded):
    r = auth_client.post(f"/admin/journeys/{seeded['journey_id']}/party-goals/new", data={
        "name": "Library Trip",
        "target_amount": "200",
        "min_individual_contribution": "50",
    }, follow_redirects=True)
    assert r.status_code == 200
    assert b"Library Trip" in r.data


def test_admin_side_quest_crud(auth_client, seeded):
    r = auth_client.post(f"/admin/quests/{seeded['quest_id']}/side-quests/new", data={
        "name": "Read before bed",
        "currency_reward": "3",
        "repeat_type": "daily",
    }, follow_redirects=True)
    assert r.status_code == 200
    assert b"Read before bed" in r.data


def test_admin_quest_detail(auth_client, seeded):
    r = auth_client.get(f"/admin/quests/{seeded['quest_id']}")
    assert r.status_code == 200
    assert b"Pokemon" in r.data


def test_admin_chain_crud(auth_client, seeded, app):
    # Create chain
    r = auth_client.post(f"/admin/quests/{seeded['quest_id']}/chains/new", data={
        "name": "The Lost Treasure",
        "currency_reward": "50",
        "visibility_mode": "checklist_sequential",
    }, follow_redirects=True)
    assert r.status_code == 200
    assert b"The Lost Treasure" in r.data

    # Get chain id
    with app.app_context():
        chain = SideQuestChain.query.filter_by(name="The Lost Treasure").first()
        chain_id = chain.id

    # Add step
    r = auth_client.post(f"/admin/chains/{chain_id}/steps/new", data={
        "name": "Find the Map",
    }, follow_redirects=True)
    assert r.status_code == 200
    assert b"Find the Map" in r.data


def test_admin_achievements_page(auth_client):
    r = auth_client.get("/admin/achievements")
    assert r.status_code == 200
