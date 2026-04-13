from __future__ import annotations

from flask import Flask

from config import Config, missing_env_keys
from models import db, login_manager
from routes import get_active_user, is_guest_mode
from routes.api import api_bp
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.finance import finance_bp
from routes.onboarding import onboarding_bp
from routes.planner import planner_bp


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    login_manager.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(onboarding_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(planner_bp)
    app.register_blueprint(finance_bp)
    app.register_blueprint(api_bp)

    @app.context_processor
    def inject_globals():
        return {
            "active_user": get_active_user(),
            "guest_mode": is_guest_mode(),
            "missing_api_keys": missing_env_keys(),
        }

    with app.app_context():
        db.create_all()

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=app.config.get("DEBUG", False))
