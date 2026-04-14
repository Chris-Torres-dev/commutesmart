from __future__ import annotations

import logging

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user

from extensions import limiter
from models import db
from models.user import User
from routes import get_onboarding_data, persist_profile_for_user, sanitize_lower, validate_input

auth_bp = Blueprint("auth", __name__)
logger = logging.getLogger(__name__)


def validate_password(password: str) -> str | None:
    if len(password) < 8:
        return "Password must be at least 8 characters and contain a number"
    if not any(char.isdigit() for char in password):
        return "Password must be at least 8 characters and contain a number"
    return None


@auth_bp.route("/")
def landing():
    if current_user.is_authenticated or session.get("guest_mode") or session.get("is_guest"):
        return redirect(url_for("dashboard.home"))
    return render_template("auth/landing.html")


@auth_bp.route("/login", methods=["GET"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    return render_template("auth/login.html")


@auth_bp.route("/login", methods=["POST"])
@limiter.limit("10 per minute")
def login_submit():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    email = sanitize_lower(request.form.get("email", ""))
    password = request.form.get("password", "")
    email_error = validate_input(email, 254, "Email")
    password_error = validate_input(password, 128, "Password")

    if email_error or password_error:
        flash("Incorrect email or password", "warning")
        return render_template("auth/login.html"), 200

    user = User.query.filter_by(email=email).first()

    if user and user.check_password(password):
        login_user(user, remember=True)
        session.pop("guest_mode", None)
        session.pop("is_guest", None)
        flash("Welcome back. Your commute plan is ready.", "success")
        return redirect(url_for("dashboard.home"))

    masked_email = f"{email[:3]}***" if email else "***"
    logger.warning("Failed login attempt for email: %s from IP: %s", masked_email, request.remote_addr)
    flash("Incorrect email or password", "warning")
    return render_template("auth/login.html"), 200


@auth_bp.route("/signup", methods=["GET"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    return render_template("auth/signup.html")


@auth_bp.route("/signup", methods=["POST"])
@limiter.limit("5 per minute")
def signup_submit():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    email = sanitize_lower(request.form.get("email", ""))
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")
    password_error = validate_password(password)
    email_error = validate_input(email, 254, "Email")
    confirm_error = validate_input(confirm_password, 128, "Password confirmation")
    password_length_error = validate_input(password, 128, "Password")

    if email_error or confirm_error or password_length_error:
        flash("We couldn't create that account. Check your details and try again.", "warning")
    elif not email or "@" not in email:
        flash("Add a valid email so we can save your plans.", "warning")
    elif password_error:
        flash(password_error, "warning")
    elif password != confirm_password:
        flash("Your passwords didn't match. Give that another shot.", "warning")
    elif User.query.filter_by(email=email).first():
        flash("We couldn't create that account. Check your details and try again.", "warning")
    else:
        user = User(email=email, is_guest=False)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user, remember=True)

        if session.get("onboarding_data"):
            persist_profile_for_user(user, get_onboarding_data())
        session.pop("guest_mode", None)
        session.pop("is_guest", None)

        flash("Account created. Let's finish your commute setup.", "success")
        return redirect(url_for("onboarding.step", step=1))

    return render_template("auth/signup.html"), 200


@auth_bp.route("/guest")
def guest():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    session["guest_mode"] = True
    session["is_guest"] = True
    session.setdefault("onboarding_data", get_onboarding_data())
    session.modified = True
    flash("You're in guest mode - save your data by signing up anytime.", "info")
    return redirect(url_for("dashboard.home"))


@auth_bp.route("/logout")
def logout():
    if current_user.is_authenticated:
        logout_user()
    session.pop("guest_mode", None)
    session.pop("is_guest", None)
    session.pop("onboarding_data", None)
    flash("You're all set. Come back anytime.", "info")
    return redirect(url_for("auth.landing"))
