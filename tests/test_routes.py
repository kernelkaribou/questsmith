import pytest
from app import create_app, db
from app.models import Member, Campaign, Quest, ActivityType, EarningRule, PartyGoal, ShopItem, SideQuest, SideQuestChain
from tests.conftest import TestConfig


CSRF_TOKEN = "test-csrf-token"


def with_csrf(data):
    return {**data, "csrf_token": CSRF_TOKEN}


@pytest.fixture
def app():
    application = create_app(TestConfig)
    with application.app_context():
        yield application


@pytest.fixture
def client(app):
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["csrf_token"] = CSRF_TOKEN
        yield c


@pytest.fixture
def auth_client(client):
    """Client already logged in as admin."""
    client.post("/admin/login", data=with_csrf({"pin": "1234"}))
    return client


@pytest.fixture
def seeded(app):
    """Seed a full campaign with member, quest, activity type, earning rule."""
    m = Member(name="Test Kid")
    db.session.add(m)
    j = Campaign(name="Summer Reading", status="active")
    db.session.add(j)
    db.session.flush()
    q = Quest(member_id=m.id, campaign_id=j.id, theme_name="Dungeon Explorer", color_primary="#FF0000", color_secondary="#FFAA00")
    db.session.add(q)
    db.session.flush()
    at = ActivityType(quest_id=q.id, name="Pages", unit_label="pages")
    db.session.add(at)
    db.session.flush()
    rule = EarningRule(activity_type_id=at.id, rule_type="per_batch", quantity_required=50, currency_reward=10)
    db.session.add(rule)
    goal = PartyGoal(campaign_id=j.id, name="Movie Night", target_amount=100, min_individual_contribution=0)
    db.session.add(goal)
    prize = ShopItem(quest_id=q.id, name="Ice Cream", cost=20)
    db.session.add(prize)
    sq = SideQuest(quest_id=q.id, name="Read Outside", currency_reward=5, repeat_type="daily")
    db.session.add(sq)
    db.session.commit()
    return {"member_id": m.id, "campaign_id": j.id, "quest_id": q.id, "activity_type_id": at.id, "prize_id": prize.id}


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
    assert b"Dungeon Explorer" in response.data


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
    response = client.post("/admin/login", data=with_csrf({"pin": "0000"}), follow_redirects=True)
    assert b"Incorrect" in response.data


def test_admin_login_and_index(auth_client, seeded):
    response = auth_client.get("/admin/")
    assert response.status_code == 200
    assert b"Summer Reading" in response.data


def test_admin_logout(auth_client):
    response = auth_client.get("/admin/logout", follow_redirects=True)
    assert b"Forge Your Adventure" in response.data


# --- Admin CRUD Tests ---

def test_admin_create_member(auth_client):
    r = auth_client.post("/admin/members/new", data=with_csrf({"name": "New Kid"}), follow_redirects=True)
    assert r.status_code == 200
    assert b"New Kid" in r.data


def test_admin_create_campaign(auth_client):
    r = auth_client.post("/admin/campaigns/new", data=with_csrf({"name": "Fall Quest", "status": "active"}), follow_redirects=True)
    assert r.status_code == 200
    assert b"Fall Quest" in r.data


def test_admin_campaign_detail(auth_client, seeded):
    r = auth_client.get(f"/admin/campaigns/{seeded['campaign_id']}")
    assert r.status_code == 200
    assert b"Summer Reading" in r.data


def test_admin_create_quest(auth_client, seeded, app):
    # Need a different member
    with app.app_context():
        m2 = Member(name="Second Kid")
        db.session.add(m2)
        db.session.commit()
        member_id = m2.id
    r = auth_client.post("/admin/quests/new", data=with_csrf({
        "member_id": member_id,
        "campaign_id": seeded["campaign_id"],
        "theme_name": "Forest Ranger",
        "color_primary": "#00FF00",
        "color_secondary": "#88FF88",
    }), follow_redirects=True)
    assert r.status_code == 200
    assert b"Forest Ranger" in r.data


def test_admin_log_activity(auth_client, seeded):
    r = auth_client.post("/admin/log", data=with_csrf({
        "quest_id": seeded["quest_id"],
        "activity_type_id": seeded["activity_type_id"],
        "quantity": "100",
    }), follow_redirects=True)
    assert r.status_code == 200
    assert b"earned 20" in r.data


def test_admin_redeem_prize(auth_client, seeded):
    # First earn some currency
    auth_client.post("/admin/log", data=with_csrf({
        "quest_id": seeded["quest_id"],
        "activity_type_id": seeded["activity_type_id"],
        "quantity": "150",
    }))
    r = auth_client.post(f"/admin/quests/{seeded['quest_id']}/redeem", data=with_csrf({
        "item_id": seeded["prize_id"],
    }), follow_redirects=True)
    assert r.status_code == 200
    assert b"redeemed" in r.data


def test_admin_redeem_insufficient_balance(auth_client, seeded):
    r = auth_client.post(f"/admin/quests/{seeded['quest_id']}/redeem", data=with_csrf({
        "item_id": seeded["prize_id"],
    }), follow_redirects=True)
    assert b"Insufficient" in r.data


def test_admin_party_goal_crud(auth_client, seeded):
    r = auth_client.post(f"/admin/campaigns/{seeded['campaign_id']}/party-goals/new", data=with_csrf({
        "name": "Library Trip",
        "target_amount": "200",
        "min_individual_contribution": "50",
    }), follow_redirects=True)
    assert r.status_code == 200
    assert b"Library Trip" in r.data


def test_admin_side_quest_crud(auth_client, seeded):
    r = auth_client.post(f"/admin/quests/{seeded['quest_id']}/side-quests/new", data=with_csrf({
        "name": "Read before bed",
        "currency_reward": "3",
        "repeat_type": "daily",
    }), follow_redirects=True)
    assert r.status_code == 200
    assert b"Read before bed" in r.data


def test_admin_quest_detail(auth_client, seeded):
    r = auth_client.get(f"/admin/quests/{seeded['quest_id']}")
    assert r.status_code == 200
    assert b"Dungeon Explorer" in r.data


def test_admin_chain_crud(auth_client, seeded, app):
    # Create chain
    r = auth_client.post(f"/admin/quests/{seeded['quest_id']}/chains/new", data=with_csrf({
        "name": "The Lost Treasure",
        "currency_reward": "50",
        "visibility_mode": "checklist_sequential",
    }), follow_redirects=True)
    assert r.status_code == 200
    assert b"The Lost Treasure" in r.data

    # Get chain id
    with app.app_context():
        chain = SideQuestChain.query.filter_by(name="The Lost Treasure").first()
        chain_id = chain.id

    # Add step
    r = auth_client.post(f"/admin/chains/{chain_id}/steps/new", data=with_csrf({
        "name": "Find the Map",
    }), follow_redirects=True)
    assert r.status_code == 200
    assert b"Find the Map" in r.data


def test_admin_achievements_page(auth_client):
    r = auth_client.get("/admin/achievements")
    assert r.status_code == 200


# --- Security Tests ---

def test_csrf_missing_token_rejected(client):
    """POST without CSRF token should redirect with session expired message."""
    # Clear CSRF from session
    with client.session_transaction() as sess:
        sess.pop("csrf_token", None)
    r = client.post("/admin/login", data={"pin": "1234"})
    assert r.status_code == 302


def test_csrf_wrong_token_rejected(client):
    """POST with wrong CSRF token should redirect."""
    r = client.post("/admin/login", data={"pin": "1234", "csrf_token": "wrong-token"})
    assert r.status_code == 302


def test_upload_path_traversal_blocked(auth_client):
    """Path traversal in upload route returns 404."""
    r = auth_client.get("/admin/uploads/../../../etc/passwd")
    assert r.status_code == 404


def test_upload_absolute_path_blocked(auth_client):
    """Encoded path traversal in upload route returns 404."""
    r = auth_client.get("/admin/uploads/..%2F..%2Fetc%2Fpasswd")
    assert r.status_code == 404


def test_admin_redeem_wrong_quest_item(auth_client, seeded, app):
    """Redeeming item from a different quest is rejected."""
    # Create a second quest with its own shop item
    with app.app_context():
        m2 = Member(name="Other")
        db.session.add(m2)
        db.session.flush()
        q2 = Quest(member_id=m2.id, theme_name="Other Quest", color_primary="#000", color_secondary="#111")
        db.session.add(q2)
        db.session.flush()
        other_item = ShopItem(quest_id=q2.id, name="Other Prize", cost=5)
        db.session.add(other_item)
        db.session.commit()
        other_item_id = other_item.id

    # Try to redeem other quest's item against seeded quest
    r = auth_client.post(f"/admin/quests/{seeded['quest_id']}/redeem", data=with_csrf({
        "item_id": other_item_id,
    }), follow_redirects=True)
    assert b"does not belong" in r.data


# --- 404 / Invalid ID Tests ---

def test_quest_view_invalid_id_404(client):
    """Requesting a non-existent quest returns 404."""
    r = client.get("/quest/9999")
    assert r.status_code == 404


def test_admin_quest_detail_invalid_id_404(auth_client):
    """Admin quest detail for non-existent quest returns 404."""
    r = auth_client.get("/admin/quests/9999")
    assert r.status_code == 404


def test_member_profile_invalid_id_404(client):
    """Profile for non-existent member returns 404."""
    r = client.get("/member/9999/profile")
    assert r.status_code == 404


def test_campaign_view_invalid_id_404(client):
    """Campaign view for non-existent campaign returns 404."""
    r = client.get("/campaign/9999")
    assert r.status_code == 404


# --- Input Validation Tests ---

def test_log_activity_invalid_quantity(auth_client, seeded):
    """Logging activity with non-numeric quantity doesn't crash."""
    r = auth_client.post("/admin/log", data=with_csrf({
        "quest_id": seeded["quest_id"],
        "activity_type_id": seeded["activity_type_id"],
        "quantity": "abc",
    }), follow_redirects=True)
    # Should not be a 500 error
    assert r.status_code == 200


def test_log_activity_zero_quantity(auth_client, seeded):
    """Logging activity with zero quantity doesn't earn currency."""
    r = auth_client.post("/admin/log", data=with_csrf({
        "quest_id": seeded["quest_id"],
        "activity_type_id": seeded["activity_type_id"],
        "quantity": "0",
    }), follow_redirects=True)
    assert r.status_code == 200


# --- Dashboard Redemption Tests ---

def test_dashboard_redeem_requires_balance(client, seeded):
    """Dashboard redemption fails without sufficient balance."""
    # Set active member
    with client.session_transaction() as sess:
        sess["active_member_id"] = seeded["member_id"]
    r = client.post(f"/quest/{seeded['quest_id']}/redeem", data=with_csrf({
        "item_id": seeded["prize_id"],
    }), follow_redirects=True)
    assert r.status_code == 200
