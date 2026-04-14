from __future__ import annotations

import json

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from config import Config
from extensions import limiter
from models import db
from models.saved_plan import SavedPlan
from routes import (
    budget_recommendation,
    get_guest_saved_plan,
    get_onboarding_data,
    login_or_guest_required,
    safe_float,
    safe_int,
    sanitize,
    sanitize_choice_list,
    set_guest_saved_plan,
    validate_input,
)
from services.ai_service import get_recommendation
from services.car_service import calculate_car_cost
from services.citibike_service import get_station_status
from services.maps_service import get_route
from services.mta_service import get_mta_snapshot

planner_bp = Blueprint("planner", __name__, url_prefix="/plan")
ALLOWED_SUBWAY_LINES = {"A", "C", "E", "B", "D", "F", "M", "G", "J", "Z", "N", "Q", "R", "W", "L", "1", "2", "3", "4", "5", "6", "S", "SI", "SIR"}


def _normalize_profile_input() -> dict:
    data = get_onboarding_data()
    values = request.values

    if values.get("origin"):
        origin = sanitize(values.get("origin", ""))
        error = validate_input(origin, 255, "Origin")
        if error:
            flash(error, "warning")
        else:
            data["home_address"] = origin
    if values.get("destination"):
        destination = sanitize(values.get("destination", ""))
        error = validate_input(destination, 255, "Destination")
        if error:
            flash(error, "warning")
        else:
            data["school_address"] = destination
    if values.get("school_name"):
        school_name = sanitize(values.get("school_name", ""))
        error = validate_input(school_name, 120, "School name")
        if error:
            flash(error, "warning")
        else:
            data["school_name"] = school_name
    if values.get("days_per_week"):
        data["days_per_week"] = safe_int(values.get("days_per_week", data["days_per_week"]), int(data["days_per_week"]), minimum=1, maximum=7)
    if values.get("trips_per_day"):
        data["trips_per_day"] = safe_int(values.get("trips_per_day", data["trips_per_day"]), int(data["trips_per_day"]), minimum=1, maximum=4)
    if values.get("weekly_budget"):
        data["weekly_budget"] = safe_float(values.get("weekly_budget", data["weekly_budget"]), float(data["weekly_budget"]), minimum=10.0, maximum=300.0)
    if values.get("transport_modes"):
        data["transport_modes"] = sanitize_choice_list(
            request.values.getlist("transport_modes"),
            allowed={"subway", "bus", "bike", "car"},
            max_items=4,
            normalize="lower",
        ) or data["transport_modes"]
    if values.get("subway_lines"):
        data["subway_lines"] = sanitize_choice_list(
            request.values.getlist("subway_lines"),
            allowed=ALLOWED_SUBWAY_LINES,
            max_items=8,
            normalize="upper",
        )

    data["origin"] = data.get("home_address") or "Brooklyn, NY"
    data["destination"] = data.get("school_address") or data.get("school_name") or "Hunter College, New York, NY"
    return data


def build_commute_plans(profile_data: dict) -> list[dict]:
    days = int(profile_data.get("days_per_week") or 4)
    trips = int(profile_data.get("trips_per_day") or 2)
    modes = profile_data.get("transport_modes") or ["subway"]
    origin = profile_data.get("origin") or profile_data.get("home_address") or "Brooklyn, NY"
    destination = profile_data.get("destination") or profile_data.get("school_address") or "Hunter College, New York, NY"

    plans: list[dict] = []
    if "subway" in modes or "bus" in modes:
        transit_route = get_route(origin, destination, mode="transit")
        pay_per_ride = round(Config.OMNY_PER_RIDE * days * trips, 2)
        plans.append(
            {
                "plan_name": "Pay-per-ride",
                "mode": "subway",
                "weekly_cost": pay_per_ride,
                "duration_minutes": round(transit_route["duration_seconds"] / 60),
                "best_for": "Lighter commute weeks",
                "summary": "Best when your class schedule changes often.",
                "icon": "fa-train-subway",
                "estimated": transit_route["estimated"],
                "distance_miles": round(transit_route["distance_meters"] / 1609.34, 2),
            }
        )
        plans.append(
            {
                "plan_name": "OMNY weekly cap",
                "mode": "subway",
                "weekly_cost": Config.OMNY_WEEKLY_CAP,
                "duration_minutes": round(transit_route["duration_seconds"] / 60),
                "best_for": "Frequent riders",
                "summary": "Locks in transit spend once your rides stack up.",
                "icon": "fa-wallet",
                "estimated": transit_route["estimated"],
                "distance_miles": round(transit_route["distance_meters"] / 1609.34, 2),
            }
        )

    if "bike" in modes:
        bike_route = get_route(origin, destination, mode="bicycling")
        bike_cost = round(
            (Config.CITIBIKE_MONTHLY / 4.33) if days >= 4 else min(days * Config.CITIBIKE_DAY_PASS, days * trips * Config.CITIBIKE_SINGLE_RIDE),
            2,
        )
        plans.append(
            {
                "plan_name": "Citi Bike flex plan",
                "mode": "bike",
                "weekly_cost": bike_cost,
                "duration_minutes": round(bike_route["duration_seconds"] / 60),
                "best_for": "Short hops and flexibility",
                "summary": "Great when your campus is within a few miles.",
                "icon": "fa-bicycle",
                "estimated": bike_route["estimated"],
                "distance_miles": round(bike_route["distance_meters"] / 1609.34, 2),
            }
        )

    if "car" in modes:
        car_cost = calculate_car_cost(
            origin,
            destination,
            days_per_week=days,
            trips_per_day=trips,
            mpg=profile_data.get("car_mpg"),
        )
        plans.append(
            {
                "plan_name": "Drive",
                "mode": "car",
                "weekly_cost": car_cost["total"],
                "duration_minutes": round(car_cost["drive_time"] / 60),
                "best_for": "Door-to-door speed",
                "summary": "Fastest when you need control, but cost climbs fast.",
                "icon": "fa-car-side",
                "estimated": False,
                "distance_miles": car_cost["distance_miles"],
                "breakdown": {
                    "gas": car_cost["gas"],
                    "tolls": car_cost["tolls"],
                    "parking": car_cost["parking"],
                    "total": car_cost["total"],
                },
                "needs_toll_confirmation": car_cost["needs_toll_confirmation"],
                "confirmation_prompt": car_cost["confirmation_prompt"],
            }
        )

    if not plans:
        walk_route = get_route(origin, destination, mode="walking")
        plans.append(
            {
                "plan_name": "Walking estimate",
                "mode": "walking",
                "weekly_cost": 0.0,
                "duration_minutes": round(walk_route["duration_seconds"] / 60),
                "best_for": "Closest campus days",
                "summary": "Fallback plan when no transport modes are selected.",
                "icon": "fa-person-walking",
                "estimated": True,
                "distance_miles": round(walk_route["distance_meters"] / 1609.34, 2),
            }
        )

    return plans


def _sorted_plans(plans: list[dict], sort_by: str) -> list[dict]:
    if sort_by == "fastest":
        return sorted(plans, key=lambda plan: (plan.get("duration_minutes", 0), plan.get("weekly_cost", 0)))
    return sorted(plans, key=lambda plan: (plan.get("weekly_cost", 0), plan.get("duration_minutes", 0)))


@planner_bp.route("", methods=["GET", "POST"], strict_slashes=False)
@login_or_guest_required
@limiter.limit("30 per minute")
def results():
    profile_data = _normalize_profile_input()
    sort_by = sanitize(request.values.get("sort", "cheapest")) or "cheapest"
    if sort_by not in {"cheapest", "fastest"}:
        sort_by = "cheapest"
    plans = build_commute_plans(profile_data)
    ordered_plans = _sorted_plans(plans, sort_by)
    cheapest_plan = min(plans, key=lambda plan: plan.get("weekly_cost", float("inf")))
    fastest_plan = min(plans, key=lambda plan: plan.get("duration_minutes", float("inf")))
    mta_snapshot = get_mta_snapshot(profile_data.get("subway_lines"))
    citibike_snapshot = get_station_status(limit=4) if "bike" in profile_data.get("transport_modes", []) else None
    recommendation = get_recommendation(
        profile_data,
        plans,
        context={"sort": sort_by, "mta_alerts": mta_snapshot.get("subway_alerts", [])[:2]},
    )

    return render_template(
        "planner/results.html",
        data=profile_data,
        plans=ordered_plans,
        sort_by=sort_by,
        cheapest_plan_name=cheapest_plan["plan_name"],
        fastest_plan_name=fastest_plan["plan_name"],
        recommendation=recommendation,
        preview=budget_recommendation(profile_data),
        saved_plan=get_guest_saved_plan() if not current_user.is_authenticated else None,
        citibike_snapshot=citibike_snapshot,
    )


@planner_bp.route("/select", methods=["POST"])
@login_or_guest_required
def select_plan():
    raw_plan = request.form.get("plan_data", "{}")
    error = validate_input(raw_plan, 10000, "Plan data")
    if error:
        flash("We couldn't save that plan right now. Please try again.", "warning")
        return redirect(url_for("planner.results"))

    try:
        plan = json.loads(raw_plan)
    except json.JSONDecodeError:
        flash("We couldn't save that plan right now. Please try again.", "warning")
        return redirect(url_for("planner.results"))

    if current_user.is_authenticated:
        SavedPlan.query.filter_by(user_id=current_user.id, is_active=True).update({"is_active": False})
        saved_plan = SavedPlan(user_id=current_user.id, plan_name=plan.get("plan_name", "Saved plan"), plan_data=plan, is_active=True)
        db.session.add(saved_plan)
        db.session.commit()
        flash(f"{plan.get('plan_name', 'Plan')} saved to your dashboard.", "success")
    else:
        set_guest_saved_plan(plan)
        flash(f"{plan.get('plan_name', 'Plan')} saved in this guest session.", "info")

    return redirect(url_for("planner.results"))
