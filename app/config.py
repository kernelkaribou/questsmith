import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.environ.get(
        "DATABASE_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "readers_quest.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ADMIN_PIN = os.environ.get("ADMIN_PIN", "1234")
