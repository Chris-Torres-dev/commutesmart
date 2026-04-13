from __future__ import annotations

import logging
import time
from typing import Any

from config import Config
from services import cache_is_fresh, safe_get_json

logger = logging.getLogger(__name__)

_citibike_cache: dict[str, Any] | None = None
_citibike_last_fetched: float | None = None


def get_station_status(limit: int = 8) -> dict[str, Any] | None:
    global _citibike_cache, _citibike_last_fetched

    if _citibike_cache and cache_is_fresh(_citibike_last_fetched, Config.CITIBIKE_CACHE_DURATION):
        return _citibike_cache

    try:
        payload = safe_get_json("https://gbfs.citibikenyc.com/gbfs/en/station_status.json")
        stations = payload.get("data", {}).get("stations", [])
        ranked = sorted(stations, key=lambda item: item.get("num_bikes_available", 0), reverse=True)
        _citibike_cache = {
            "stations": ranked[:limit],
            "source": "gbfs",
            "updated_at": time.time(),
        }
        _citibike_last_fetched = time.time()
        return _citibike_cache
    except Exception as exc:  # pragma: no cover - network-dependent
        logger.warning("Citi Bike fetch failed: %s", exc)
        return _citibike_cache


if __name__ == "__main__":
    print("Testing citibike_service...")
    result = get_station_status()
    print(f"Result: {result}")
    print("✅ citibike_service OK" if result is not None else "⚠ citibike_service returned None (check network)")
