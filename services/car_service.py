from __future__ import annotations

import logging
import time
from typing import Any

from config import Config
from services import make_cache_key, safe_get_json
from services.maps_service import get_route, infer_borough

logger = logging.getLogger(__name__)

_gas_cache: dict[str, tuple[float, float]] = {}


def get_live_gas_price() -> float:
    cache_key = make_cache_key("nyc-gas")
    cached = _gas_cache.get(cache_key)
    if cached and (time.time() - cached[1]) < Config.GAS_CACHE_DURATION:
        return cached[0]

    if not Config.COLLECT_API_KEY:
        return Config.DEFAULT_GAS_PRICE_NYC

    headers = {"authorization": f"apikey {Config.COLLECT_API_KEY}", "content-type": "application/json"}
    candidate_endpoints = [
        ("https://api.collectapi.com/gasPrice/allUsaPrice", {}),
        ("https://api.collectapi.com/gasPrice/stateUsaPrice", {"state": "new york"}),
    ]

    for url, params in candidate_endpoints:
        try:
            payload = safe_get_json(url, headers=headers, params=params, timeout=8)
            result = payload.get("result")
            if isinstance(result, dict):
                for value in result.values():
                    if isinstance(value, (int, float)):
                        _gas_cache[cache_key] = (float(value), time.time())
                        return float(value)
            if isinstance(result, list):
                for row in result:
                    price = row.get("gasoline") or row.get("price") or row.get("amount")
                    if isinstance(price, (int, float)):
                        _gas_cache[cache_key] = (float(price), time.time())
                        return float(price)
                    if isinstance(price, str):
                        cleaned = price.replace("$", "").strip()
                        try:
                            value = float(cleaned)
                        except ValueError:
                            continue
                        _gas_cache[cache_key] = (value, time.time())
                        return value
        except Exception as exc:  # pragma: no cover - network-dependent
            logger.warning("CollectAPI gas lookup failed at %s: %s", url, exc)

    return Config.DEFAULT_GAS_PRICE_NYC


def toll_detector(origin: str, destination: str) -> dict[str, Any]:
    origin_borough = infer_borough(origin)
    destination_borough = infer_borough(destination)
    tolls: list[str] = []
    needs_confirmation = False

    if "staten island" in origin.lower() or "staten island" in destination.lower():
        tolls.append("verrazano")
    if ("manhattan" in {origin_borough, destination_borough}) and ({origin_borough, destination_borough} & {"brooklyn", "queens", "bronx"}):
        tolls.append("congestion_pricing_enter_manhattan")
        needs_confirmation = True
    if any(keyword in f"{origin} {destination}".lower() for keyword in ["new jersey", "nj", "jersey city", "newark"]):
        tolls.append("lincoln_tunnel")

    unique_tolls = []
    for toll in tolls:
        if toll not in unique_tolls:
            unique_tolls.append(toll)

    return {
        "toll_names": unique_tolls,
        "toll_cost": round(sum(Config.TOLLS.get(name, 0) for name in unique_tolls), 2),
        "needs_confirmation": needs_confirmation,
        "confirmation_prompt": "Does your route cross any tolls?" if needs_confirmation else "",
    }


def calculate_car_cost(
    origin: str,
    destination: str,
    *,
    days_per_week: int = 1,
    trips_per_day: int = 2,
    mpg: float | None = None,
) -> dict[str, Any]:
    route = get_route(origin, destination, mode="driving")
    distance_miles = round(route["distance_meters"] / 1609.34, 2)
    weekly_distance = distance_miles * days_per_week * trips_per_day
    effective_mpg = float(mpg or Config.DEFAULT_MPG)
    gas_price = get_live_gas_price()
    gas_cost = round((weekly_distance / max(effective_mpg, 1.0)) * gas_price, 2)

    toll_info = toll_detector(origin, destination)
    weekly_tolls = round(toll_info["toll_cost"] * days_per_week, 2)

    destination_borough = infer_borough(destination)
    parking_daily = Config.PARKING_ESTIMATES.get(destination_borough, Config.PARKING_ESTIMATES["manhattan"])
    parking_total = round(parking_daily * days_per_week, 2)

    total = round(gas_cost + weekly_tolls + parking_total, 2)
    return {
        "gas": gas_cost,
        "tolls": weekly_tolls,
        "parking": parking_total,
        "total": total,
        "drive_time": route["duration_seconds"],
        "distance_miles": distance_miles,
        "gas_price": gas_price,
        "toll_names": toll_info["toll_names"],
        "needs_toll_confirmation": toll_info["needs_confirmation"],
        "confirmation_prompt": toll_info["confirmation_prompt"],
    }


if __name__ == "__main__":
    print("Testing car_service...")
    result = calculate_car_cost("Brooklyn, NY", "Baruch College, New York, NY", days_per_week=4)
    print(f"Result: {result}")
    print("✅ car_service OK" if result is not None else "⚠ car_service returned None (check API key)")
