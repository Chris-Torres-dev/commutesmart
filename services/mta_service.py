from __future__ import annotations

import logging
import time
from typing import Any

from config import Config
from services import cache_is_fresh, logger as shared_logger

logger = logging.getLogger(__name__)
logger.setLevel(shared_logger.level)

try:
    from nyct_gtfs import NYCTFeed
except Exception:  # pragma: no cover - optional dependency handling
    NYCTFeed = None

_mta_cache: dict[str, tuple[dict[str, Any], float]] = {}
mta_failure_count = 0
mta_last_failure_time: float | None = None


def _fallback_alerts(mode: str) -> dict[str, Any]:
    if mode == "subway":
        alerts = [
            {
                "line": "system",
                "headline": "Live subway data unavailable",
                "detail": "We'll lean on your saved route and fallback estimates for now.",
                "severity": "info",
            }
        ]
    else:
        alerts = [
            {
                "line": "bus",
                "headline": "Bus feed unavailable",
                "detail": "Bus timing is in fallback mode right now.",
                "severity": "info",
            }
        ]
    return {"alerts": alerts, "source": "fallback", "updated_at": time.time()}


def _in_cooldown() -> bool:
    if mta_failure_count < 3 or mta_last_failure_time is None:
        return False
    return (time.time() - mta_last_failure_time) < Config.MTA_RETRY_COOLDOWN


def _filter_alerts(data: dict[str, Any], requested_lines: list[str] | None) -> dict[str, Any]:
    if not requested_lines:
        return data
    requested = {line.upper() for line in requested_lines}
    alerts = [alert for alert in data.get("alerts", []) if alert.get("line", "").upper() in requested or alert.get("line") == "system"]
    return {**data, "alerts": alerts or data.get("alerts", [])}


def _remember_failure() -> None:
    global mta_failure_count, mta_last_failure_time
    mta_failure_count += 1
    mta_last_failure_time = time.time()


def _remember_success() -> None:
    global mta_failure_count, mta_last_failure_time
    mta_failure_count = 0
    mta_last_failure_time = None


def get_subway_alerts(lines: list[str] | None = None) -> dict[str, Any]:
    cache_entry = _mta_cache.get("subway")
    if cache_entry and cache_is_fresh(cache_entry[1], Config.MTA_SUBWAY_CACHE_DURATION):
        return _filter_alerts(cache_entry[0], lines)

    if _in_cooldown():
        return _filter_alerts(cache_entry[0], lines) if cache_entry else _fallback_alerts("subway")

    if NYCTFeed is None:
        fallback = _fallback_alerts("subway")
        _mta_cache["subway"] = (fallback, time.time())
        return _filter_alerts(fallback, lines)

    monitored_lines = [line.upper() for line in (lines or ["1", "A", "Q"])]
    try:
        alerts = []
        for line in monitored_lines:
            feed = NYCTFeed(line)
            trips = feed.filter_trips(line_id=line)
            alerts.append(
                {
                    "line": line,
                    "headline": f"{line} line live",
                    "detail": f"{len(trips)} active trains found in the real-time feed.",
                    "severity": "info" if trips else "warning",
                }
            )
        data = {"alerts": alerts, "source": "nyct_gtfs", "updated_at": time.time()}
        _mta_cache["subway"] = (data, time.time())
        _remember_success()
        return _filter_alerts(data, lines)
    except Exception as exc:  # pragma: no cover - network-dependent
        logger.warning("Subway feed failed: %s", exc)
        _remember_failure()
        return _filter_alerts(cache_entry[0], lines) if cache_entry else _fallback_alerts("subway")


def get_bus_alerts(routes: list[str] | None = None) -> dict[str, Any]:
    cache_entry = _mta_cache.get("bus")
    if cache_entry and cache_is_fresh(cache_entry[1], Config.MTA_BUS_CACHE_DURATION):
        return cache_entry[0]

    if _in_cooldown():
        return cache_entry[0] if cache_entry else _fallback_alerts("bus")

    try:
        watched = routes or ["M15", "Bx12", "B44"]
        alerts = [
            {
                "line": route,
                "headline": f"{route} bus fallback status",
                "detail": "Bus live data is limited in this MVP, so we're showing safe fallback messaging.",
                "severity": "info",
            }
            for route in watched
        ]
        data = {"alerts": alerts, "source": "fallback", "updated_at": time.time()}
        _mta_cache["bus"] = (data, time.time())
        _remember_success()
        return data
    except Exception as exc:  # pragma: no cover
        logger.warning("Bus feed failed: %s", exc)
        _remember_failure()
        return cache_entry[0] if cache_entry else _fallback_alerts("bus")


def get_mta_snapshot(lines: list[str] | None = None, routes: list[str] | None = None) -> dict[str, Any]:
    subway = get_subway_alerts(lines)
    bus = get_bus_alerts(routes)
    return {
        "subway_alerts": subway.get("alerts", []),
        "bus_alerts": bus.get("alerts", []),
        "source": "live" if subway.get("source") == "nyct_gtfs" else "fallback",
    }


if __name__ == "__main__":
    print("Testing mta_service...")
    result = get_subway_alerts()
    print(f"Result: {result}")
    print("✅ mta_service OK" if result is not None else "⚠ mta_service returned None (check API key)")
