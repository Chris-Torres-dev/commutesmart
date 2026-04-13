from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from flask import Blueprint, render_template
from flask_login import current_user

from config import Config
from models.spend_log import SpendLog
from routes import current_week_start, get_guest_spend_logs, get_onboarding_data, login_or_guest_required

finance_bp = Blueprint("finance", __name__, url_prefix="/finance")


def _serialize_db_logs() -> list[dict]:
    if not current_user.is_authenticated:
        return []
    serialized = []
    for log in SpendLog.query.filter_by(user_id=current_user.id).order_by(SpendLog.week_start_date.asc()).all():
        serialized.append(
            {
                "week_start_date": log.week_start_date.isoformat(),
                "amount_spent": float(log.amount_spent),
                "transport_mode": log.transport_mode,
                "notes": log.notes or "",
                "created_at": log.created_at.isoformat(),
            }
        )
    return serialized


def _mock_logs(profile_data: dict) -> list[dict]:
    budget = float(profile_data.get("weekly_budget") or 34)
    base = max(10.0, min(Config.OMNY_WEEKLY_CAP, budget - 3))
    week_start = current_week_start()
    logs = []
    for offset in range(7, -1, -1):
        amount = round(base + ((offset % 3) - 1) * 2.5, 2)
        logs.append(
            {
                "week_start_date": (week_start - timedelta(weeks=offset)).isoformat(),
                "amount_spent": max(6.0, amount),
                "transport_mode": "subway",
                "notes": "Mock data until you add your own spend.",
                "created_at": date.today().isoformat(),
            }
        )
    return logs


def get_spend_logs(profile_data: dict) -> list[dict]:
    logs = _serialize_db_logs() if current_user.is_authenticated else get_guest_spend_logs()
    return logs or _mock_logs(profile_data)


def build_finance_payload(profile_data: dict) -> dict:
    logs = get_spend_logs(profile_data)
    budget = float(profile_data.get("weekly_budget") or 34)
    week_start = current_week_start()

    weekly_map = defaultdict(float)
    monthly_map = defaultdict(float)
    for log in logs:
        weekly_map[log["week_start_date"]] += float(log["amount_spent"])
        month_key = log["week_start_date"][:7]
        monthly_map[month_key] += float(log["amount_spent"])

    weekly_points = []
    for offset in range(7, -1, -1):
        current = week_start - timedelta(weeks=offset)
        key = current.isoformat()
        weekly_points.append({"label": current.strftime("%b %d"), "amount": round(weekly_map.get(key, 0.0), 2)})

    monthly_points = []
    month_anchor = date.today().replace(day=1)
    for offset in range(5, -1, -1):
        month = (month_anchor.replace(day=15) - timedelta(days=offset * 30)).replace(day=1)
        key = month.strftime("%Y-%m")
        monthly_points.append({"label": month.strftime("%b"), "amount": round(monthly_map.get(key, 0.0), 2)})

    current_week_spend = round(weekly_map.get(week_start.isoformat(), weekly_points[-1]["amount"]), 2)
    this_month_key = date.today().strftime("%Y-%m")
    this_month_spend = round(monthly_map.get(this_month_key, sum(point["amount"] for point in weekly_points[-4:])), 2)
    semester_total = round(sum(point["amount"] for point in weekly_points), 2)
    current_floor = min(Config.OMNY_WEEKLY_CAP, Config.OMNY_PER_RIDE * int(profile_data.get("days_per_week") or 4) * int(profile_data.get("trips_per_day") or 2))
    saved = round(max(0.0, (budget - current_floor) * 16), 2)

    return {
        "metrics": {
            "week": current_week_spend,
            "month": this_month_spend,
            "semester": semester_total,
            "saved": saved,
        },
        "weekly_points": weekly_points,
        "monthly_points": monthly_points,
        "budget": budget,
        "logs": logs[-5:][::-1],
        "budget_status": {
            "percent": round((current_week_spend / max(budget, 1)) * 100, 1),
            "remaining": round(max(0.0, budget - current_week_spend), 2),
        },
    }


def build_export_summary(profile_data: dict, payload: dict) -> str:
    metrics = payload["metrics"]
    return "\n".join(
        [
            "CommuteSmart budget summary",
            f"Weekly budget: ${payload['budget']:.2f}",
            f"This week spent: ${metrics['week']:.2f}",
            f"This month spent: ${metrics['month']:.2f}",
            f"Semester total: ${metrics['semester']:.2f}",
            f"Potential semester savings: ${metrics['saved']:.2f}",
            f"Preferred modes: {', '.join(profile_data.get('transport_modes') or ['subway'])}",
        ]
    )


@finance_bp.route("", strict_slashes=False)
@login_or_guest_required
def dashboard():
    data = get_onboarding_data()
    payload = build_finance_payload(data)
    return render_template("finance/dashboard.html", data=data, finance=payload, export_text=build_export_summary(data, payload))
