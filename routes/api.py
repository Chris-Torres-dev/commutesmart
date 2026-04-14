from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user

from extensions import limiter
from models import db
from models.spend_log import SpendLog
from routes import (
    add_guest_spend_log,
    current_week_start,
    get_onboarding_data,
    login_or_guest_required,
    persist_profile_for_user,
    update_onboarding_data,
)
from routes.finance import build_export_summary, build_finance_payload
from routes.planner import build_commute_plans
from services.ai_service import answer_commute_question

api_bp = Blueprint("api", __name__)


@api_bp.route("/api/ping")
def ping():
    return jsonify({"status": "ok"})


@api_bp.route("/api/chat", methods=["POST"])
@login_or_guest_required
@limiter.limit("10 per minute")
def chat():
    payload = request.get_json(silent=True) or {}
    message = payload.get("message", "").strip()
    profile = get_onboarding_data()
    plans = build_commute_plans({**profile, "origin": profile.get("home_address"), "destination": profile.get("school_address")})
    response = answer_commute_question(message or "What's my best route today?", profile, plans)
    return jsonify(response)


@api_bp.route("/api/budget", methods=["POST"])
@login_or_guest_required
def update_budget():
    payload = request.get_json(silent=True) or {}
    budget = float(payload.get("weekly_budget") or get_onboarding_data().get("weekly_budget") or 34)
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
    amount = float(payload.get("amount") or 0)
    mode = payload.get("transport_mode", "subway")
    notes = payload.get("notes", "")
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


@api_bp.route("/health")
@limiter.exempt
def health():
    return {"status": "ok", "app": "CommuteSmart", "version": "1.0"}, 200
