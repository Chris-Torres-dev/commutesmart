from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from flask_login import current_user

from extensions import limiter
from models import db
from models.profile import Profile
from models.spend_log import SpendLog
from routes import (
    add_guest_spend_log,
    current_week_start,
    get_onboarding_data,
    login_or_guest_required,
    persist_profile_for_user,
    safe_float,
    sanitize,
    sanitize_choice_list,
    update_onboarding_data,
    validate_input,
)
from routes.finance import build_export_summary, build_finance_payload
from routes.planner import build_commute_plans
from services import ai_service

api_bp = Blueprint("api", __name__)


def get_current_week_start():
    today = datetime.utcnow().date()
    return today - timedelta(days=today.weekday())


@api_bp.route("/api/ping")
def ping():
    return jsonify({"status": "ok"})


@api_bp.route("/api/chat", methods=["POST"])
@login_or_guest_required
@limiter.limit("10 per minute")
def chat():
    payload = request.get_json(silent=True) or {}
    user_message = sanitize(payload.get("message", "")).strip()
    error = validate_input(user_message, 500, "Message")
    if error:
        return jsonify({"ok": False, "error": error}), 400
    if not user_message:
        return {"reply": "What would you like to know about your commute?"}, 200

    context = {
        "home": "unknown",
        "school": "unknown",
        "budget": 34.00,
        "methods": ["subway"],
        "days_per_week": 4,
    }

    if current_user.is_authenticated:
        profile = Profile.query.filter_by(user_id=current_user.id).first()
        if profile:
            context.update(
                {
                    "home": profile.home_address or "unknown",
                    "school": profile.school_name or profile.school_address or "unknown",
                    "budget": float(profile.weekly_budget or 34.00),
                    "methods": profile.transport_modes or ["subway"],
                    "days_per_week": int(profile.days_per_week or 4),
                }
            )
    else:
        guest_profile = get_onboarding_data()
        context.update(
            {
                "home": guest_profile.get("home_address") or "unknown",
                "school": guest_profile.get("school_name") or guest_profile.get("school_address") or "unknown",
                "budget": float(guest_profile.get("weekly_budget") or 34.00),
                "methods": guest_profile.get("transport_modes") or ["subway"],
                "days_per_week": int(guest_profile.get("days_per_week") or 4),
            }
        )

    reply = ai_service.get_chat_reply(user_message, context)
    return {"reply": reply}, 200


@api_bp.route("/api/budget", methods=["POST"])
@login_or_guest_required
def update_budget():
    payload = request.get_json(silent=True) or {}
    budget = safe_float(payload.get("weekly_budget"), float(get_onboarding_data().get("weekly_budget") or 34), minimum=10.0, maximum=300.0)
    updates = {
        "weekly_budget": budget,
        "budget_alert_50": bool(payload.get("budget_alert_50", True)),
        "budget_alert_80": bool(payload.get("budget_alert_80", True)),
    }
    data = update_onboarding_data(updates)
    if current_user.is_authenticated:
        persist_profile_for_user(current_user, data)
    finance = build_finance_payload(data)
    return jsonify({"ok": True, "budget": budget, "finance": finance})


@api_bp.route("/api/spend-log", methods=["POST"])
@login_or_guest_required
def add_spend_log():
    payload = request.get_json(silent=True) or {}
    amount = safe_float(payload.get("amount"), 0.0, minimum=0.0, maximum=500.0)
    modes = sanitize_choice_list([payload.get("transport_mode", "subway")], allowed={"subway", "bus", "bike", "car", "walking"}, max_items=1, normalize="lower")
    mode = modes[0] if modes else "subway"
    notes = sanitize(payload.get("notes", ""))
    error = validate_input(notes, 255, "Notes")
    if error:
        return jsonify({"ok": False, "error": error}), 400

    week_start = current_week_start()

    if current_user.is_authenticated:
        log = SpendLog(
            user_id=current_user.id,
            week_start_date=week_start,
            amount_spent=amount,
            transport_mode=mode,
            notes=notes,
        )
        db.session.add(log)
        db.session.commit()
    else:
        add_guest_spend_log(
            {
                "week_start_date": week_start.isoformat(),
                "amount_spent": amount,
                "transport_mode": mode,
                "notes": notes,
                "created_at": datetime.utcnow().isoformat(),
            }
        )

    finance = build_finance_payload(get_onboarding_data())
    return jsonify({"ok": True, "finance": finance})


@api_bp.route("/api/export")
@login_or_guest_required
def export_summary():
    profile = get_onboarding_data()
    finance = build_finance_payload(profile)
    return jsonify({"text": build_export_summary(profile, finance)})


@api_bp.route("/api/budget/add", methods=["POST"])
def budget_add():
    if current_user.is_authenticated:
        payload = request.get_json(silent=True) or {}
        amount = safe_float(payload.get("amount"), 0.0, minimum=0.0, maximum=9999.0)
        if 0 < amount < 10000:
            profile = Profile.query.filter_by(user_id=current_user.id).first()
            entry = SpendLog(
                user_id=current_user.id,
                amount_spent=amount,
                week_start_date=get_current_week_start(),
                transport_mode=(profile.transport_modes[0] if profile and profile.transport_modes else "subway"),
                notes="Dashboard budget bar",
                created_at=datetime.utcnow(),
            )
            db.session.add(entry)
            db.session.commit()
    return {"ok": True}, 200


@api_bp.route("/api/budget/reset", methods=["POST"])
def budget_reset():
    if current_user.is_authenticated:
        week_start = get_current_week_start()
        SpendLog.query.filter_by(user_id=current_user.id, week_start_date=week_start).delete()
        db.session.commit()
    return {"ok": True}, 200


@api_bp.route("/api/budget/delete-last", methods=["POST"])
def budget_delete_last():
    if current_user.is_authenticated:
        last = SpendLog.query.filter_by(user_id=current_user.id).order_by(SpendLog.created_at.desc()).first()
        if last:
            db.session.delete(last)
            db.session.commit()
    return {"ok": True}, 200


@api_bp.route("/health")
@limiter.exempt
def health():
    return {"status": "ok", "app": "CommuteSmart", "version": "1.0"}, 200
