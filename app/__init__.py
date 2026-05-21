import secrets
import time
import logging

from flask import Flask, request, session, g
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

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("questsmith")

    db.init_app(app)

    with app.app_context():
        @event.listens_for(db.engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    @app.before_request
    def start_timer():
        g.start_time = time.perf_counter()

    @app.before_request
    def csrf_protect():
        if request.method == "POST":
            if request.endpoint == "admin.login":
                return
            token = session.get("csrf_token")
            form_token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not token or token != form_token:
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return {"error": "CSRF token invalid"}, 403
                from flask import redirect, flash
                flash("Session expired. Please try again.")
                return redirect(request.url)

    @app.after_request
    def log_request_time(response):
        if hasattr(g, "start_time"):
            elapsed = (time.perf_counter() - g.start_time) * 1000
            logger.info(f"{request.method} {request.path} - {response.status_code} - {elapsed:.1f}ms")
            response.headers["X-Response-Time"] = f"{elapsed:.1f}ms"
            response.headers["Server-Timing"] = f"total;dur={elapsed:.1f}"
        return response

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
        import sqlalchemy
        try:
            db.create_all()
        except sqlalchemy.exc.OperationalError:
            pass  # Race between gunicorn workers; table already created

    return app
