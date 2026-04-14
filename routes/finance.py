from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from flask import Blueprint, render_template
from flask_login import current_user

from config import Config
from extensions import limiter
from models.spend_log import SpendLog
from routes import current_week_start, get_guest_spend_logs, get_onboarding_data, login_or_guest_required

finance_bp = Blueprint("finance", __name__, url_prefix="/finance")


def get_week_start(weeks_ago: int = 0):
    today = datetime.utcnow().date()
    monday = today - timedelta(days=today.weekday())
    return monday - timedelta(weeks=weeks_ago)


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


def get_spend_logs(profile_data: dict) -> list[dict]:
    logs = _serialize_db_logs() if current_user.is_authenticated else get_guest_spend_logs()
    return logs or []


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
    if not current_user.is_authenticated and not logs:
        saved = 0.0

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
@limiter.limit("30 per minute")
def dashboard():
    data = get_onboarding_data()
    payload = build_finance_payload(data)

    weekly_data = []
    monthly_data = []
    total_spent = 0.0
    total_saved = 0.0
    semester_spent = 0.0
    budget = float(data.get("weekly_budget") or 34.0)
    is_guest = not current_user.is_authenticated

    if current_user.is_authenticated:
        for i in range(7, -1, -1):
            week_start = get_week_start(weeks_ago=i)
            entries = SpendLog.query.filter(
                SpendLog.user_id == current_user.id,
                SpendLog.week_start_date == week_start,
            ).all()
            week_total = sum(entry.amount_spent for entry in entries)
            weekly_data.append({"label": week_start.strftime("%b %d"), "amount": round(week_total, 2)})

        now = datetime.utcnow()
        for i in range(5, -1, -1):
            month_date = now - timedelta(days=30 * i)
            month_start = month_date.replace(day=1).date()
            next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
            entries = SpendLog.query.filter(
                SpendLog.user_id == current_user.id,
                SpendLog.created_at >= datetime.combine(month_start, time.min),
                SpendLog.created_at < datetime.combine(next_month, time.min),
            ).all()
            month_total = sum(entry.amount_spent for entry in entries)
            monthly_data.append({"label": month_date.strftime("%b"), "amount": round(month_total, 2)})

        all_entries = SpendLog.query.filter_by(user_id=current_user.id).all()
        total_spent = round(sum(entry.amount_spent for entry in all_entries), 2)
        profile = current_user.profile
        budget = float(profile.weekly_budget if profile and profile.weekly_budget is not None else budget)
        pay_per_ride_cost = 48.00
        weeks_using_app = len({entry.week_start_date for entry in all_entries})
        without_app = pay_per_ride_cost * weeks_using_app
        total_saved = max(0.0, round(without_app - total_spent, 2))
        semester_spent = total_spent
    else:
        today = datetime.utcnow()
        for i in range(7, -1, -1):
            week = today - timedelta(weeks=i)
            weekly_data.append({"label": week.strftime("%b %d"), "amount": 0})
        for i in range(5, -1, -1):
            month = today - timedelta(days=30 * i)
            monthly_data.append({"label": month.strftime("%b"), "amount": 0})
        budget = 34.00

    return render_template(
        "finance/dashboard.html",
        data=data,
        finance=payload,
        export_text=build_export_summary(data, payload),
        weekly_data=weekly_data,
        monthly_data=monthly_data,
        total_spent=total_spent,
        total_saved=total_saved,
        semester_spent=semester_spent,
        budget=budget,
        is_guest=is_guest,
    )
