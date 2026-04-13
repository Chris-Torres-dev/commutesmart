from __future__ import annotations

from flask import Blueprint, render_template
from flask_login import current_user

from config import Config
from models.saved_plan import SavedPlan
from routes import get_guest_saved_plan, get_onboarding_data, login_or_guest_required
from routes.finance import build_finance_payload
from routes.planner import build_commute_plans
from services.ai_service import get_recommendation
from services.mta_service import get_mta_snapshot
from services.news_service import get_news

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


def _budget_tone(percent: float) -> str:
    if percent >= 100:
        return "orange"
    if percent >= 80:
        return "yellow"
    return "sage"


@dashboard_bp.route("", strict_slashes=False)
@login_or_guest_required
def home():
    data = get_onboarding_data()

    try:
        plans = build_commute_plans({**data, "origin": data.get("home_address"), "destination": data.get("school_address")})
    except Exception:
        plans = [
            {
                "plan_name": "Pay-per-ride",
                "mode": "subway",
                "weekly_cost": min(Config.OMNY_WEEKLY_CAP, Config.OMNY_PER_RIDE * int(data.get("days_per_week", 4)) * int(data.get("trips_per_day", 2))),
                "duration_minutes": 42,
                "best_for": "Fallback route",
            }
        ]

    cheapest = min(plans, key=lambda plan: plan.get("weekly_cost", float("inf")))
    fastest = min(plans, key=lambda plan: plan.get("duration_minutes", float("inf")))

    try:
        mta_snapshot = get_mta_snapshot()
    except Exception:
        mta_snapshot = {"subway_alerts": [], "bus_alerts": [], "source": "fallback"}

    try:
        news_cards = get_news()[:5]
    except Exception:
        news_cards = Config.FALLBACK_NEWS

    finance_payload = build_finance_payload(data)
    recommendation = get_recommendation(
        data,
        plans,
        context={"dashboard": True, "alerts": mta_snapshot.get("subway_alerts", [])[:2]},
    )

    active_plan = None
    if current_user.is_authenticated:
        saved = SavedPlan.query.filter_by(user_id=current_user.id, is_active=True).order_by(SavedPlan.created_at.desc()).first()
        active_plan = saved.plan_data if saved else None
    else:
        active_plan = get_guest_saved_plan()

    return render_template(
        "dashboard/home.html",
        data=data,
        cheapest=cheapest,
        fastest=fastest,
        mta_snapshot=mta_snapshot,
        finance=finance_payload,
        news_cards=news_cards,
        recommendation=recommendation,
        active_plan=active_plan,
        budget_tone=_budget_tone(finance_payload["budget_status"]["percent"]),
    )
