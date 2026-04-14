from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from config import Config
from extensions import limiter
from routes import (
    DEFAULT_ONBOARDING_DATA,
    budget_recommendation,
    get_onboarding_data,
    login_or_guest_required,
    persist_profile_for_user,
    update_onboarding_data,
)

onboarding_bp = Blueprint("onboarding", __name__, url_prefix="/onboarding")


def _to_bool(value: str | None) -> bool:
    return value in {"on", "true", "1", "yes"}


def _apply_step_update(step: int) -> dict:
    if step == 1:
        return {"home_address": request.form.get("home_address", "").strip()}
    if step == 2:
        return {
            "school_name": request.form.get("school_name", "").strip(),
            "school_address": request.form.get("school_address", "").strip(),
        }
    if step == 3:
        return {
            "days_per_week": int(request.form.get("days_per_week", 4)),
            "trips_per_day": int(request.form.get("trips_per_day", 2)),
            "commute_time_preference": request.form.get("commute_time_preference", "AM"),
        }
    if step == 4:
        return {
            "transport_modes": request.form.getlist("transport_modes") or ["subway"],
            "car_mpg": float(request.form.get("car_mpg") or Config.DEFAULT_MPG),
        }
    if step == 5:
        budget_choice = request.form.get("budget_choice", "")
        custom_budget = request.form.get("custom_budget", "").strip()
        selected_budget = custom_budget if budget_choice == "custom" and custom_budget else budget_choice
        return {
            "weekly_budget": float(selected_budget or DEFAULT_ONBOARDING_DATA["weekly_budget"]),
            "budget_alert_50": _to_bool(request.form.get("budget_alert_50")),
            "budget_alert_80": _to_bool(request.form.get("budget_alert_80")),
        }
    return {}


@onboarding_bp.route("/")
@login_or_guest_required
def index():
    return redirect(url_for("onboarding.step", step=1))


@onboarding_bp.route("/skip")
@login_or_guest_required
def skip_all():
    update_onboarding_data(DEFAULT_ONBOARDING_DATA)
    if current_user.is_authenticated:
        persist_profile_for_user(current_user, get_onboarding_data())
    flash("Default commute setup loaded. You can refine it any time.", "info")
    return redirect(url_for("dashboard.home"))


@onboarding_bp.route("/<int:step>/skip")
@login_or_guest_required
def skip_step(step: int):
    if step >= 5:
        if current_user.is_authenticated:
            persist_profile_for_user(current_user, get_onboarding_data())
        flash("Onboarding wrapped. Your dashboard is ready.", "success")
        return redirect(url_for("dashboard.home"))
    return redirect(url_for("onboarding.step", step=step + 1))


@onboarding_bp.route("/<int:step>", methods=["GET", "POST"])
@login_or_guest_required
@limiter.limit("60 per minute")
def step(step: int):
    if step < 1 or step > 5:
        return redirect(url_for("onboarding.step", step=1))

    if request.method == "POST":
        data = update_onboarding_data(_apply_step_update(step))
        if step == 5:
            if current_user.is_authenticated:
                persist_profile_for_user(current_user, data)
            flash("Profile saved. Here's your best shot for this week.", "success")
            return redirect(url_for("dashboard.home"))
        return redirect(url_for("onboarding.step", step=step + 1))

    data = get_onboarding_data()
    preview = budget_recommendation(data)
    return render_template(
        f"onboarding/step{step}.html",
        step=step,
        progress=step * 20,
        data=data,
        preview=preview,
        schools=Config.DEFAULT_SCHOOLS,
    )
