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


def answer_commute_question(
    user_message: str,
    profile: dict[str, Any],
    plans: list[dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fallback = {
        "reply": "Right now I'd stick with your cheapest saved route and re-check around rush hour for any changes.",
        "source": "fallback",
    }
    plans = plans or []
    prompt = json.dumps(
        {
            "message": user_message,
            "profile": profile,
            "plans": plans,
            "context": context or {},
            "schema": {"reply": "string"},
        }
    )
    cache_key = make_cache_key("chat", hashlib.sha1(prompt.encode("utf-8")).hexdigest())
    return _call_openai_safe(prompt, cache_key, fallback)


if __name__ == "__main__":
    print("Testing ai_service...")
    result = get_recommendation(
        {"weekly_budget": 30, "transport_modes": ["subway", "bike"], "days_per_week": 4, "trips_per_day": 2},
        [{"plan_name": "OMNY weekly cap", "mode": "subway", "weekly_cost": 34}],
    )
    print(f"Result: {result}")
    print("✅ ai_service OK" if result is not None else "⚠ ai_service returned None (check API key)")
