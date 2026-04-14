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
    safe_float,
    safe_int,
    sanitize,
    sanitize_choice_list,
    update_onboarding_data,
    validate_input,
)

onboarding_bp = Blueprint("onboarding", __name__, url_prefix="/onboarding")


def _to_bool(value: str | None) -> bool:
    return value in {"on", "true", "1", "yes"}


def _validate_step_update(step: int, payload: dict) -> str | None:
    if step == 1:
        return validate_input(payload.get("home_address", ""), 255, "Home address")
    if step == 2:
        return validate_input(payload.get("school_name", ""), 120, "School name") or validate_input(
            payload.get("school_address", ""),
            255,
            "School address",
        )
    return None


def _apply_step_update(step: int) -> dict:
    if step == 1:
        return {"home_address": sanitize(request.form.get("home_address", ""))}
    if step == 2:
        return {
            "school_name": sanitize(request.form.get("school_name", "")),
            "school_address": sanitize(request.form.get("school_address", "")),
        }
    if step == 3:
        return {
            "days_per_week": safe_int(request.form.get("days_per_week", 4), 4, minimum=1, maximum=7),
            "trips_per_day": safe_int(request.form.get("trips_per_day", 2), 2, minimum=1, maximum=4),
            "commute_time_preference": sanitize(request.form.get("commute_time_preference", "AM")) or "AM",
        }
    if step == 4:
        return {
            "transport_modes": sanitize_choice_list(
                request.form.getlist("transport_modes"),
                allowed={"subway", "bus", "bike", "car"},
                max_items=4,
                normalize="lower",
            )
            or ["subway"],
            "car_mpg": safe_float(request.form.get("car_mpg"), Config.DEFAULT_MPG, minimum=10.0, maximum=100.0),
        }
    if step == 5:
        budget_choice = sanitize(request.form.get("budget_choice", ""))
        custom_budget = sanitize(request.form.get("custom_budget", ""))
        selected_budget = custom_budget if budget_choice == "custom" and custom_budget else budget_choice
        return {
            "weekly_budget": safe_float(
                selected_budget,
                float(DEFAULT_ONBOARDING_DATA["weekly_budget"]),
                minimum=10.0,
                maximum=300.0,
            ),
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
        updates = _apply_step_update(step)
        validation_error = _validate_step_update(step, updates)
        if validation_error:
            flash(validation_error, "warning")
            return redirect(url_for("onboarding.step", step=step))

        data = update_onboarding_data(updates)
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
