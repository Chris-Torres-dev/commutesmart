from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from flask import Blueprint, render_template
from flask_login import current_user

from extensions import limiter
from models.spend_log import SpendLog
from routes import (
    current_week_start,
    get_guest_spend_logs,
    get_onboarding_data,
    login_or_guest_required,
)

finance_bp = Blueprint("finance", __name__, url_prefix="/finance")


def get_week_start(weeks_ago: int = 0, *, anchor: date | None = None) -> date:
    anchor_date = anchor or date.today()
    monday = anchor_date - timedelta(days=anchor_date.weekday())
    return monday - timedelta(weeks=weeks_ago)


def get_month_start(
    months_ago: int = 0,
    *,
    anchor: date | None = None,
) -> date:
    anchor_date = (anchor or date.today()).replace(day=1)
    month = anchor_date.month - months_ago
    year = anchor_date.year
    while month <= 0:
        year -= 1
        month += 12
    return date(year, month, 1)


def _parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _recent_log_sort_key(log: dict) -> tuple[datetime, float]:
    created_at = _parse_datetime(log.get("created_at")) or datetime.min
    return created_at, float(log.get("amount_spent") or 0.0)


def _serialize_db_logs() -> list[dict]:
    if not current_user.is_authenticated:
        return []
    serialized = []
    query = (
        SpendLog.query.filter_by(user_id=current_user.id)
        .order_by(SpendLog.created_at.asc())
        .all()
    )
    for log in query:
        serialized.append(
            {
                "week_start_date": log.week_start_date.isoformat(),
                "amount_spent": float(log.amount_spent),
                "transport_mode": log.transport_mode,
                "notes": log.notes or "",
                "created_at": (
                    log.created_at.isoformat() if log.created_at else ""
                ),
            }
        )
    return serialized


def get_spend_logs(profile_data: dict) -> list[dict]:
    logs = (
        _serialize_db_logs()
        if current_user.is_authenticated
        else get_guest_spend_logs()
    )
    return logs or []


def build_finance_payload(profile_data: dict) -> dict:
    logs = get_spend_logs(profile_data)
    budget = float(profile_data.get("weekly_budget") or 34)
    today = date.today()
    week_start = current_week_start()

    weekly_map: dict[date, float] = defaultdict(float)
    monthly_map: dict[date, float] = defaultdict(float)
    total_spent = 0.0
    active_weeks: set[date] = set()
    for log in logs:
        amount = float(log.get("amount_spent") or 0.0)
        total_spent += amount

        week_key = _parse_date(log.get("week_start_date"))
        if week_key:
            weekly_map[week_key] += amount
            active_weeks.add(week_key)

        created_at = _parse_datetime(log.get("created_at"))
        month_source = created_at.date() if created_at else week_key
        if month_source:
            monthly_map[month_source.replace(day=1)] += amount

    weekly_points = []
    for offset in range(7, -1, -1):
        current = get_week_start(offset, anchor=today)
        weekly_points.append(
            {
                "label": current.strftime("%b %d"),
                "amount": round(weekly_map.get(current, 0.0), 2),
            }
        )

    monthly_points = []
    for offset in range(5, -1, -1):
        month = get_month_start(offset, anchor=today)
        monthly_points.append(
            {
                "label": month.strftime("%b"),
                "amount": round(monthly_map.get(month, 0.0), 2),
            }
        )

    current_week_spend = round(weekly_map.get(week_start, 0.0), 2)
    current_month = get_month_start(anchor=today)
    this_month_spend = round(monthly_map.get(current_month, 0.0), 2)
    total_spent = round(total_spent, 2)
    semester_total = total_spent
    baseline_weekly_cost = 48.0
    saved = 0.0
    if active_weeks:
        saved = round(
            max(0.0, (baseline_weekly_cost * len(active_weeks)) - total_spent),
            2,
        )
    recent_logs = sorted(logs, key=_recent_log_sort_key, reverse=True)[:5]

    return {
        "metrics": {
            "week": current_week_spend,
            "month": this_month_spend,
            "total": total_spent,
            "semester": semester_total,
            "saved": saved,
        },
        "weekly_points": weekly_points,
        "monthly_points": monthly_points,
        "budget": budget,
        "logs": recent_logs,
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
            "Preferred modes: "
            f"{', '.join(profile_data.get('transport_modes') or ['subway'])}",
        ]
    )


@finance_bp.route("", strict_slashes=False)
@login_or_guest_required
@limiter.limit("30 per minute")
def dashboard():
    data = get_onboarding_data()
    payload = build_finance_payload(data)
    weekly_data = payload["weekly_points"]
    monthly_data = payload["monthly_points"]
    total_spent = payload["metrics"]["total"]
    total_saved = payload["metrics"]["saved"]
    semester_spent = payload["metrics"]["semester"]
    budget = payload["budget"]
    is_guest = not current_user.is_authenticated

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
