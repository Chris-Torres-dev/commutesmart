from __future__ import annotations

import logging
import time
from typing import Any

from config import Config
from services import make_cache_key, safe_get_json

logger = logging.getLogger(__name__)

_maps_cache: dict[str, tuple[dict[str, Any], float]] = {}

_DISTANCE_MATRIX = {
    ("manhattan", "manhattan"): 3.2,
    ("manhattan", "brooklyn"): 7.5,
    ("manhattan", "queens"): 9.2,
    ("manhattan", "bronx"): 11.0,
    ("manhattan", "staten_island"): 16.0,
    ("brooklyn", "brooklyn"): 5.5,
    ("brooklyn", "queens"): 8.0,
    ("brooklyn", "bronx"): 15.0,
    ("brooklyn", "staten_island"): 14.0,
    ("queens", "queens"): 6.8,
    ("queens", "bronx"): 13.0,
    ("queens", "staten_island"): 20.0,
    ("bronx", "bronx"): 6.4,
    ("bronx", "staten_island"): 24.0,
    ("staten_island", "staten_island"): 8.5,
}

_SPEEDS = {"transit": 14, "driving": 18, "bicycling": 9, "walking": 3}


def infer_borough(address: str) -> str:
    value = (address or "").lower()
    borough_map = {
        "manhattan": ["manhattan", "new york, ny 100", "new york ny 100", "harlem", "soho"],
        "brooklyn": ["brooklyn", "bklyn"],
        "queens": ["queens", "jamaica", "astoria", "flushing"],
        "bronx": ["bronx"],
        "staten_island": ["staten island"],
    }
    for borough, hints in borough_map.items():
        if any(hint in value for hint in hints):
            return borough
    return "manhattan"


def _lookup_distance(origin: str, destination: str) -> float:
    borough_pair = tuple(sorted((infer_borough(origin), infer_borough(destination))))
    return _DISTANCE_MATRIX.get(borough_pair, 8.5)


def _fallback_estimate(origin: str, destination: str, mode: str) -> dict[str, Any]:
    distance_miles = round(_lookup_distance(origin, destination) * 1.4, 2)
    speed = _SPEEDS.get(mode, _SPEEDS["transit"])
    duration_hours = max(distance_miles / speed, 0.15)
    return {
        "duration_seconds": int(duration_hours * 3600),
        "distance_meters": int(distance_miles * 1609.34),
        "summary": f"Estimated {mode} route",
        "estimated": True,
        "source": "fallback",
    }


def get_route(origin: str, destination: str, mode: str = "transit") -> dict[str, Any]:
    cache_key = make_cache_key(origin, destination, mode)
    cached = _maps_cache.get(cache_key)
    if cached and (time.time() - cached[1]) < Config.MAPS_CACHE_DURATION:
        return cached[0]

    if not origin or not destination:
        result = _fallback_estimate(origin or "manhattan", destination or "manhattan", mode)
        _maps_cache[cache_key] = (result, time.time())
        return result

    if not Config.GOOGLE_MAPS_API_KEY:
        result = _fallback_estimate(origin, destination, mode)
        _maps_cache[cache_key] = (result, time.time())
        return result

    params = {
        "origin": origin,
        "destination": destination,
        "mode": mode,
        "key": Config.GOOGLE_MAPS_API_KEY,
    }
    try:
        payload = safe_get_json("https://maps.googleapis.com/maps/api/directions/json", params=params, timeout=10)
        routes = payload.get("routes", [])
        if payload.get("status") != "OK" or not routes:
            raise ValueError(payload.get("status", "Unknown Maps error"))
        leg = routes[0]["legs"][0]
        result = {
            "duration_seconds": leg["duration"]["value"],
            "distance_meters": leg["distance"]["value"],
            "summary": routes[0].get("summary") or leg.get("end_address", "Google Maps route"),
            "estimated": False,
            "source": "google_maps",
        }
    except Exception as exc:  # pragma: no cover - network-dependent
        logger.warning("Maps API fallback triggered: %s", exc)
        result = _fallback_estimate(origin, destination, mode)

    _maps_cache[cache_key] = (result, time.time())
    return result


if __name__ == "__main__":
    print("Testing maps_service...")
    result = get_route("Brooklyn, NY", "Hunter College, New York, NY", "transit")
    print(f"Result: {result}")
    print("✅ maps_service OK" if result is not None else "⚠ maps_service returned None (check API key)")
