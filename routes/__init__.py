from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import wraps
from typing import Any

from flask import flash, session
from flask_login import current_user

from config import Config

DEFAULT_ONBOARDING_DATA = {
    "home_address": "",
    "school_name": "",
    "school_address": "",
    "days_per_week": 4,
    "trips_per_day": 2,
    "commute_time_preference": "AM",
    "transport_modes": ["subway"],
    "weekly_budget": 34.0,
    "car_mpg": Config.DEFAULT_MPG,
    "budget_alert_50": True,
    "budget_alert_80": True,
}


@dataclass
class GuestUser:
    id: str = "guest-session"
    email: str = "Guest student"
    is_guest: bool = True
    is_authenticated: bool = True


def get_active_user() -> Any | None:
    if current_user.is_authenticated:
        return current_user
    if session.get("guest_mode"):
        return GuestUser()
    return None


def is_guest_mode() -> bool:
    return bool(session.get("guest_mode")) and not current_user.is_authenticated


def login_or_guest_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if current_user.is_authenticated or is_guest_mode():
            return view(*args, **kwargs)
        flash("Start with an account or continue as a guest to see your commute dashboard.", "warning")
        from flask import redirect, url_for

        return redirect(url_for("auth.landing"))

    return wrapped_view


def get_onboarding_data() -> dict[str, Any]:
    data = DEFAULT_ONBOARDING_DATA.copy()
    data.update(session.get("onboarding_data", {}))

    if current_user.is_authenticated:
        from models import db
        from models.user import User

        fresh_user = db.session.get(User, current_user.id)
        profile = fresh_user.profile if fresh_user else None
        if profile:
            data.update(
                {
                    "home_address": profile.home_address or data["home_address"],
                    "school_name": profile.school_name or data["school_name"],
                    "school_address": profile.school_address or data["school_address"],
                    "days_per_week": profile.days_per_week or data["days_per_week"],
                    "trips_per_day": profile.trips_per_day or data["trips_per_day"],
                    "commute_time_preference": profile.commute_time_preference or data["commute_time_preference"],
                    "transport_modes": profile.transport_modes or data["transport_modes"],
                    "weekly_budget": profile.weekly_budget or data["weekly_budget"],
                    "car_mpg": profile.car_mpg or data["car_mpg"],
                    "budget_alert_50": profile.budget_alert_50,
                    "budget_alert_80": profile.budget_alert_80,
                }
            )

    return data


def update_onboarding_data(updates: dict[str, Any]) -> dict[str, Any]:
    data = get_onboarding_data()
    data.update({key: value for key, value in updates.items() if value is not None})
    session["onboarding_data"] = data
    session.modified = True
    return data


def clear_guest_session() -> None:
    session.pop("guest_mode", None)
    session.pop("onboarding_data", None)


def estimate_weekly_cost(data: dict[str, Any]) -> float:
    days = int(data.get("days_per_week") or 4)
    trips = int(data.get("trips_per_day") or 2)
    modes = data.get("transport_modes") or ["subway"]

    if "bike" in modes and days >= 4:
        bike_week = round(Config.CITIBIKE_MONTHLY / 4.33, 2)
    else:
        bike_week = round(min(days * Config.CITIBIKE_DAY_PASS, trips * days * Config.CITIBIKE_SINGLE_RIDE), 2)

    transit_week = min(Config.OMNY_WEEKLY_CAP, Config.OMNY_PER_RIDE * days * trips)
    car_week = round((days * trips * 4.75) + (days * 15), 2)

    estimates = []
    if "subway" in modes or "bus" in modes:
        estimates.append(transit_week)
    if "bike" in modes:
        estimates.append(bike_week)
    if "car" in modes:
        estimates.append(car_week)

    return round(min(estimates) if estimates else transit_week, 2)


def budget_recommendation(data: dict[str, Any]) -> dict[str, float]:
    cheapest = estimate_weekly_cost(data)
    suggested = max(34.0, round(cheapest + 5, 2))
    return {"cheapest": cheapest, "suggested": suggested}


def mode_label(mode: str) -> str:
    labels = {
        "subway": "Subway",
        "bus": "Bus",
        "bike": "Citi Bike",
        "car": "Car",
        "walking": "Walking",
        "transit": "Transit",
    }
    return labels.get(mode, mode.title())


def persist_profile_for_user(user, data: dict[str, Any]):
    from models import db
    from models.profile import Profile
    from models.user import User

    fresh_user = db.session.get(User, user.id)
    if fresh_user is None:
        return None

    profile = fresh_user.profile or Profile(user_id=fresh_user.id)
    profile.home_address = data.get("home_address")
    profile.school_name = data.get("school_name")
    profile.school_address = data.get("school_address")
    profile.days_per_week = int(data.get("days_per_week") or DEFAULT_ONBOARDING_DATA["days_per_week"])
    profile.trips_per_day = int(data.get("trips_per_day") or DEFAULT_ONBOARDING_DATA["trips_per_day"])
    profile.commute_time_preference = data.get("commute_time_preference") or DEFAULT_ONBOARDING_DATA["commute_time_preference"]
    profile.transport_modes = data.get("transport_modes") or DEFAULT_ONBOARDING_DATA["transport_modes"]
    profile.weekly_budget = float(data.get("weekly_budget") or DEFAULT_ONBOARDING_DATA["weekly_budget"])
    profile.car_mpg = float(data.get("car_mpg") or Config.DEFAULT_MPG)
    profile.budget_alert_50 = bool(data.get("budget_alert_50", True))
    profile.budget_alert_80 = bool(data.get("budget_alert_80", True))

    db.session.add(profile)
    db.session.commit()
    return profile


def get_guest_spend_logs() -> list[dict[str, Any]]:
    return list(session.get("guest_spend_logs", []))


def add_guest_spend_log(entry: dict[str, Any]) -> list[dict[str, Any]]:
    logs = get_guest_spend_logs()
    logs.append(entry)
    session["guest_spend_logs"] = logs
    session.modified = True
    return logs


def get_guest_saved_plan() -> dict[str, Any] | None:
    return session.get("guest_saved_plan")


def set_guest_saved_plan(plan: dict[str, Any]) -> None:
    session["guest_saved_plan"] = plan
    session.modified = True


def current_week_start() -> date:
    today = date.today()
    return today.fromordinal(today.toordinal() - today.weekday())
