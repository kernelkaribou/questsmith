import secrets

from flask import Flask, request, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event


db = SQLAlchemy()


def create_app(config_class=None):
    app = Flask(__name__)

    if config_class:
        app.config.from_object(config_class)
    else:
        from app.config import Config
        app.config.from_object(Config)

    db.init_app(app)

    with app.app_context():
        @event.listens_for(db.engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    @app.before_request
    def csrf_protect():
        if request.method == "POST":
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return
            token = session.get("csrf_token")
            form_token = request.form.get("csrf_token")
            if not token or token != form_token:
                from flask import abort
                abort(403)

    @app.context_processor
    def inject_csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(32)
        return {"csrf_token": session["csrf_token"]}

    from app import models  # noqa: F401 - register models with SQLAlchemy

    from app.routes import admin, dashboard
    app.register_blueprint(admin.bp)
    app.register_blueprint(dashboard.bp)

    with app.app_context():
        db.create_all()

    return app
