import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", os.urandom(32).hex())
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.environ.get(
        "DATABASE_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "questsmith.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ADMIN_PIN = os.environ.get("PIN", os.environ.get("ADMIN_PIN", "1234"))
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_HTTPONLY = True
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB upload limit
