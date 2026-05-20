import os
import secrets


def _get_or_create_secret_key():
    """Get SECRET_KEY from env, or persist one in the data directory."""
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    data_dir = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
    key_file = os.path.join(data_dir, ".secret_key")
    if os.path.exists(key_file):
        with open(key_file, "r") as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    os.makedirs(data_dir, exist_ok=True)
    with open(key_file, "w") as f:
        f.write(key)
    return key


class Config:
    SECRET_KEY = _get_or_create_secret_key()
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.environ.get(
        "DATABASE_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "questsmith.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ADMIN_PIN = os.environ.get("PIN", os.environ.get("ADMIN_PIN", "1234"))
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_HTTPONLY = True
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB upload limit
