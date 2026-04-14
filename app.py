from __future__ import annotations

import os

from flask import Flask, render_template, request, session, url_for
from flask_limiter.errors import RateLimitExceeded

from config import Config, missing_env_keys
from extensions import csrf, limiter
from models import db, login_manager
from routes import get_active_user, is_guest_mode
from routes.api import api_bp
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.finance import finance_bp
from routes.onboarding import onboarding_bp
from routes.planner import planner_bp
from services.news_service import format_news_date


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)
    csrf.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(onboarding_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(planner_bp)
    app.register_blueprint(finance_bp)
    app.register_blueprint(api_bp)
    app.jinja_env.filters["format_date"] = format_news_date

    @app.context_processor
    def inject_globals():
        return {
            "active_user": get_active_user(),
            "guest_mode": is_guest_mode(),
            "missing_api_keys": missing_env_keys(),
        }

    @app.before_request
    def make_session_permanent():
        session.permanent = True

    @app.route("/robots.txt")
    def robots():
        return app.send_static_file("robots.txt")

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' cdnjs.cloudflare.com cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' fonts.googleapis.com cdnjs.cloudflare.com; "
            "font-src 'self' fonts.gstatic.com cdnjs.cloudflare.com; "
            "img-src 'self' data:; "
            "connect-src 'self'"
        )
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.errorhandler(RateLimitExceeded)
    def rate_limit_handler(e):
        back_url = request.referrer or url_for("auth.landing")
        return render_template("errors/429.html", back_url=back_url), 429

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

    with app.app_context():
        db.create_all()

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
