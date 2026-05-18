from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()


def create_app(config_class=None):
    app = Flask(__name__)

    if config_class:
        app.config.from_object(config_class)
    else:
        from app.config import Config
        app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)

    from app import models  # noqa: F401 - register models with SQLAlchemy

    from app.routes import admin, dashboard
    app.register_blueprint(admin.bp)
    app.register_blueprint(dashboard.bp)

    return app
