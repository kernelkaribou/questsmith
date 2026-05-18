import pytest
from app import create_app, db


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        yield client


def test_dashboard_index(client):
    response = client.get("/")
    assert response.status_code == 200


def test_admin_redirects_without_auth(client):
    response = client.get("/admin/")
    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]


def test_admin_login_and_index(client):
    response = client.post("/admin/login", data={"pin": "1234"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Admin" in response.data
