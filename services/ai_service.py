from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import date
from typing import Any

from openai import OpenAI

from config import Config
from routes import mode_label
from services import make_cache_key

logger = logging.getLogger(__name__)

DAILY_AI_CALL_LIMIT = Config.DAILY_AI_CALL_LIMIT
_ai_cache: dict[str, tuple[dict[str, Any], float]] = {}
_ai_counter = {"day": date.today().isoformat(), "count": 0}


def _reset_daily_counter_if_needed() -> None:
    today = date.today().isoformat()
    if _ai_counter["day"] != today:
        _ai_counter["day"] = today
        _ai_counter["count"] = 0


def _rule_based_pick(profile: dict[str, Any], plans: list[dict[str, Any]]) -> dict[str, Any]:
    budget = float(profile.get("weekly_budget") or 34)
    modes = profile.get("transport_modes") or []
    cheapest_plan = min(plans, key=lambda plan: plan.get("weekly_cost", float("inf")), default=None)
    bike_plan = next((plan for plan in plans if plan.get("mode") == "bike"), None)

    if budget < 35:
        best_plan = next((plan for plan in plans if plan.get("plan_name") == "OMNY weekly cap"), cheapest_plan)
        reason = "Your budget is tight, so a capped transit plan keeps the week predictable."
    elif bike_plan and bike_plan.get("distance_miles", 99) < 3:
        best_plan = bike_plan
        reason = "A short ride makes Citi Bike the cheapest flexible option."
    else:
        best_plan = cheapest_plan
        reason = "Pay-per-ride keeps costs low without locking you into extra spend."

    if not best_plan:
        best_plan = {
            "mode": "subway",
            "plan_name": "Pay-per-ride",
            "weekly_cost": min(Config.OMNY_WEEKLY_CAP, Config.OMNY_PER_RIDE * 8),
        }

    return {
        "best_plan": best_plan.get("plan_name") or mode_label(best_plan.get("mode", "subway")),
        "reason": reason,
        "tip": "Check your route again before the morning rush if service changes.",
        "savings_message": f"You could keep this week near ${best_plan.get('weekly_cost', 0):.0f}.",
        "source": "fallback",
    }


def _call_openai_safe(prompt: str, cache_key: str, fallback: dict[str, Any]) -> dict[str, Any]:
    _reset_daily_counter_if_needed()
    cached = _ai_cache.get(cache_key)
    if cached and (time.time() - cached[1]) < Config.AI_CACHE_DURATION:
        return cached[0]

    if not Config.OPENAI_API_KEY:
        return fallback

    if _ai_counter["count"] >= DAILY_AI_CALL_LIMIT:
        logger.warning("AI daily call limit reached; using fallback.")
        return fallback

    _ai_counter["count"] += 1

    try:
        client = OpenAI(api_key=Config.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            temperature=0.5,
            max_tokens=300,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "You are CommuteSmart, a concise NYC student commute coach. Return JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        parsed = json.loads(response.choices[0].message.content or "{}")
        parsed["source"] = "openai"
        _ai_cache[cache_key] = (parsed, time.time())
        return parsed
    except Exception as exc:  # pragma: no cover - network-dependent
        logger.warning("OpenAI recommendation failed: %s", exc)
        return fallback


def get_recommendation(profile: dict[str, Any], plans: list[dict[str, Any]], context: dict[str, Any] | None = None) -> dict[str, Any]:
    fallback = _rule_based_pick(profile, plans)
    context = context or {}
    prompt = json.dumps(
        {
            "profile": {
                "budget": profile.get("weekly_budget"),
                "methods": profile.get("transport_modes"),
                "days_per_week": profile.get("days_per_week"),
                "trips_per_day": profile.get("trips_per_day"),
            },
            "plans": plans,
            "context": context,
            "schema": {
                "best_plan": "string",
                "reason": "string",
                "tip": "string",
                "savings_message": "string",
            },
        }
    )
    cache_key = make_cache_key("recommendation", hashlib.sha1(prompt.encode("utf-8")).hexdigest())
    return _call_openai_safe(prompt, cache_key, fallback)


def rule_based_chat(user_message: str, context: dict[str, Any]) -> str:
    msg = (user_message or "").lower()
    home = context.get("home") or "your place"
    school = context.get("school") or "school"
    budget = float(context.get("budget") or 34.0)

    if any(word in msg for word in ["fastest", "quick", "fast"]):
        return f"Your fastest option from {home} to {school} is usually the subway. Check the MTA alerts above before you leave."

    if any(word in msg for word in ["cheap", "cheapest", "save", "budget"]):
        return f"With a ${budget:.0f}/week budget, OMNY weekly cap at $34 or Citi Bike plus one subway ride usually gives you the best value."

    if any(word in msg for word in ["bike", "citi"]):
        return "Citi Bike monthly is $17.99 per month, so it's strongest when you're within a few miles of campus. Check dock availability before you head out."

    if any(word in msg for word in ["rain", "weather"]):
        return "On rainy days, stick to the subway if you can. Citi Bike gets uncomfortable fast and surface routes are more likely to drag."

    if any(word in msg for word in ["today", "now", "morning", "rush"]):
        return "Check the MTA alerts section above for today's service status. During rush hour, giving yourself an extra 10 minutes is the safest move."

    return "Great question! Open the Plan page to compare your route options side by side with real commute costs."


def get_chat_reply(user_message: str, context: dict[str, Any]) -> str:
    _reset_daily_counter_if_needed()

    if _ai_counter["count"] >= DAILY_AI_CALL_LIMIT or not Config.OPENAI_API_KEY:
        return rule_based_chat(user_message, context)

    try:
        _ai_counter["count"] += 1
        client = OpenAI(api_key=Config.OPENAI_API_KEY)
        methods = context.get("methods") or ["subway"]
        system_prompt = (
            "You are CommuteSmart's AI coach for NYC students. "
            f"You are helping a student who lives near {context.get('home') or 'unknown'} "
            f"and goes to {context.get('school') or 'unknown'}. "
            f"Their weekly commute budget is ${float(context.get('budget') or 34.0):.2f}. "
            f"They use: {', '.join(methods)}. "
            f"They commute {int(context.get('days_per_week') or 4)} days a week.\n\n"
            "Answer their specific question directly and concisely. "
            "Give NYC-specific advice using real subway lines, MTA info, Citi Bike, or car costs. "
            "Keep answers under 3 sentences. Be friendly, direct, and helpful. "
            "Never give the same generic response twice - answer the specific question asked. "
            "If asked about the fastest route, give the fastest. If asked about the cheapest, give the cheapest. "
            "If you don't know exact real-time data, give your best general advice."
        )
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=150,
            temperature=0.7,
        )
        reply = response.choices[0].message.content.strip()
        return reply or rule_based_chat(user_message, context)
    except Exception as exc:  # pragma: no cover - network-dependent
        logger.error("OpenAI chat error: %s", exc)
        return rule_based_chat(user_message, context)


def answer_commute_question(
    user_message: str,
    profile: dict[str, Any],
    plans: list[dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chat_context = {
        "home": profile.get("home_address") or profile.get("origin") or "unknown",
        "school": profile.get("school_name") or profile.get("school_address") or profile.get("destination") or "unknown",
        "budget": profile.get("weekly_budget") or 34.0,
        "methods": profile.get("transport_modes") or ["subway"],
        "days_per_week": profile.get("days_per_week") or 4,
    }
    return {"reply": get_chat_reply(user_message, chat_context), "source": "fallback" if not Config.OPENAI_API_KEY else "openai"}


if __name__ == "__main__":
    print("Testing ai_service...")
    result = get_recommendation(
        {"weekly_budget": 30, "transport_modes": ["subway", "bike"], "days_per_week": 4, "trips_per_day": 2},
        [{"plan_name": "OMNY weekly cap", "mode": "subway", "weekly_cost": 34}],
    )
    print(f"Result: {result}")
    print("✅ ai_service OK" if result is not None else "⚠ ai_service returned None (check API key)")
