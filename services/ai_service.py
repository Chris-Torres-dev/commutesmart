from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import date
from typing import Any

from openai import APIConnectionError, APITimeoutError, AuthenticationError, OpenAI

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


def _openai_api_key() -> str | None:
    return os.getenv("OPENAI_API_KEY") or Config.OPENAI_API_KEY


def _chat_model_candidates() -> list[str]:
    configured_model = os.getenv("OPENAI_CHAT_MODEL")
    candidates = [configured_model, "gpt-4o-mini", "gpt-4.1-mini", "gpt-3.5-turbo"]
    return list(dict.fromkeys([model for model in candidates if model]))


def _call_openai_safe(prompt: str, cache_key: str, fallback: dict[str, Any]) -> dict[str, Any]:
    _reset_daily_counter_if_needed()
    cached = _ai_cache.get(cache_key)
    if cached and (time.time() - cached[1]) < Config.AI_CACHE_DURATION:
        return cached[0]

    api_key = _openai_api_key()
    if not api_key:
        return fallback

    if _ai_counter["count"] >= DAILY_AI_CALL_LIMIT:
        logger.warning("AI daily call limit reached; using fallback.")
        return fallback

    _ai_counter["count"] += 1

    try:
        client = OpenAI(api_key=api_key)
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


def get_chat_reply(
    user_message: str,
    context: dict[str, Any],
    history: list[dict[str, str]] | None = None,
) -> dict[str, str]:
    history = history or []
    methods = context.get("methods") or ["subway"]
    api_key = _openai_api_key()

    if not api_key:
        logger.error("OpenAI chat unavailable: OPENAI_API_KEY is not configured.")
        return {
            "reply": "I can't answer with GPT in this environment yet because OpenAI isn't configured for the app.",
            "source": "configuration_error",
        }

    system_prompt = (
        "You are CommuteSmart's AI assistant for NYC students. "
        "You know NYC subway and bus service, MTA fares, OMNY, MetroCard, Citi Bike, car commuting costs, "
        "Fair Fares, CUNY ASAP, and common student commute tradeoffs across the city. "
        "You can answer any commute or transit question, not just preset ones. "
        "You should feel like a knowledgeable NYC commuter friend: warm, practical, specific, and concise.\n\n"
        f"Student context: they live near {context.get('home') or 'unknown'}, go to {context.get('school') or 'unknown'}, "
        f"have a weekly commute budget of ${float(context.get('budget') or 34.0):.2f}, use {', '.join(methods)}, "
        f"and commute {int(context.get('days_per_week') or 4)} days per week.\n\n"
        "Use the conversation history for follow-up questions, short references, and pronouns like 'what trains?' or 'is that cheaper?'. "
        "Answer the exact question asked. Mention uncertainty briefly if exact live data is unavailable, then give the best next-step advice. "
        "Keep most answers under 4 sentences unless the user asks for more detail."
    )

    messages = [{"role": "system", "content": system_prompt}]
    for item in history[-10:]:
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:1000]})
    messages.append({"role": "user", "content": user_message})

    client = OpenAI(api_key=api_key)
    last_error: Exception | None = None

    for model_name in _chat_model_candidates():
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=220,
                temperature=0.7,
            )
            reply = (response.choices[0].message.content or "").strip()
            if reply:
                return {"reply": reply, "source": "openai"}
            logger.warning("OpenAI returned an empty reply for chat model %s.", model_name)
        except (APIConnectionError, APITimeoutError) as exc:  # pragma: no cover - network-dependent
            logger.error("OpenAI network error: %s", exc)
            return {
                "reply": "I couldn't reach OpenAI right now, so I can't answer reliably at the moment. Please try again in a minute.",
                "source": "fallback",
            }
        except AuthenticationError as exc:  # pragma: no cover - network-dependent
            logger.error("OpenAI authentication error using model %s: %s", model_name, exc)
            return {
                "reply": "I couldn't get a GPT response right now. Please try again once OpenAI is available for this app.",
                "source": "error",
            }
        except Exception as exc:  # pragma: no cover - network-dependent
            last_error = exc
            logger.error("OpenAI chat error using model %s: %s", model_name, exc)

    if last_error:
        logger.error("OpenAI chat exhausted all model options: %s", last_error)
    return {
        "reply": "I couldn't get a GPT response right now. Please try again once OpenAI is available for this app.",
        "source": "error",
    }


def answer_commute_question(
    user_message: str,
    profile: dict[str, Any],
    plans: list[dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, str]:
    chat_context = {
        "home": profile.get("home_address") or profile.get("origin") or "unknown",
        "school": profile.get("school_name") or profile.get("school_address") or profile.get("destination") or "unknown",
        "budget": profile.get("weekly_budget") or 34.0,
        "methods": profile.get("transport_modes") or ["subway"],
        "days_per_week": profile.get("days_per_week") or 4,
    }
    return get_chat_reply(user_message, chat_context, history=[])


if __name__ == "__main__":
    print("Testing ai_service...")
    result = get_recommendation(
        {"weekly_budget": 30, "transport_modes": ["subway", "bike"], "days_per_week": 4, "trips_per_day": 2},
        [{"plan_name": "OMNY weekly cap", "mode": "subway", "weekly_cost": 34}],
    )
    print(f"Result: {result}")
    print("✅ ai_service OK" if result is not None else "⚠ ai_service returned None (check API key)")
