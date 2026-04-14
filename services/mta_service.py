from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Config

logger = logging.getLogger(__name__)

MTA_FEEDS = {
    "ACE": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace",
    "BDFM": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm",
    "G": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-g",
    "JZ": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz",
    "NQRW": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw",
    "L": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l",
    "123456S": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
    "SIR": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-si",
}

MTA_ALERT_FEEDS = {
    "all_alerts": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fall-alerts.json",
    "subway_alerts": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fsubway-alerts.json",
    "bus_alerts": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fbus-alerts.json",
}

LINE_TO_FEED_KEY = {
    "A": "ACE",
    "C": "ACE",
    "E": "ACE",
    "B": "BDFM",
    "D": "BDFM",
    "F": "BDFM",
    "M": "BDFM",
    "G": "G",
    "J": "JZ",
    "Z": "JZ",
    "N": "NQRW",
    "Q": "NQRW",
    "R": "NQRW",
    "W": "NQRW",
    "L": "L",
    "1": "123456S",
    "2": "123456S",
    "3": "123456S",
    "4": "123456S",
    "5": "123456S",
    "6": "123456S",
    "S": "123456S",
    "SI": "SIR",
    "SIR": "SIR",
}

_mta_cache: dict[str, tuple[Any, float]] = {}


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


def _get_cached(cache_key: str, duration: int = 60) -> Any | None:
    cached = _mta_cache.get(cache_key)
    if cached and (time.time() - cached[1]) < duration:
        return cached[0]
    return None


def _set_cached(cache_key: str, value: Any) -> Any:
    _mta_cache[cache_key] = (value, time.time())
    return value


def _request_json(url: str, cache_key: str) -> dict[str, Any] | None:
    cached = _get_cached(cache_key, 60)
    if cached is not None:
        return cached

    try:
        response = requests.get(url, timeout=8)
        response.raise_for_status()
        return _set_cached(cache_key, response.json())
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("MTA JSON request failed for %s: %s", url, exc)
        return None


def _request_feed(url: str, cache_key: str) -> bytes | None:
    cached = _get_cached(cache_key, 60)
    if cached is not None:
        return cached

    try:
        response = requests.get(url, timeout=8)
        response.raise_for_status()
        return _set_cached(cache_key, response.content)
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("MTA realtime feed request failed for %s: %s", url, exc)
        return None


def get_feed_key_for_line(line: str | None) -> str | None:
    normalized = (line or "").strip().upper()
    if not normalized:
        return None
    return LINE_TO_FEED_KEY.get(normalized)


def get_feed_url_for_line(line: str | None) -> str | None:
    feed_key = get_feed_key_for_line(line)
    if not feed_key:
        return None
    return MTA_FEEDS.get(feed_key)


def get_line_feed(line: str | None) -> dict[str, Any] | None:
    feed_key = get_feed_key_for_line(line)
    feed_url = get_feed_url_for_line(line)
    if not feed_key or not feed_url:
        return None

    payload = _request_feed(feed_url, f"realtime:{feed_key}")
    if payload is None:
        return None

    return {
        "line": (line or "").upper(),
        "feed_key": feed_key,
        "feed_url": feed_url,
        "bytes": len(payload),
        "source": "direct_feed",
        "updated_at": time.time(),
    }


def _extract_entities(payload: dict[str, Any]) -> list[dict[str, Any]]:
    entities = payload.get("entity")
    if isinstance(entities, list):
        return entities
    data = payload.get("data")
    if isinstance(data, dict):
        entities = data.get("entity") or data.get("entities")
        if isinstance(entities, list):
            return entities
    return []


def _extract_text(text_block: Any, default: str) -> str:
    if isinstance(text_block, str) and text_block.strip():
        return text_block.strip()
    if isinstance(text_block, dict):
        translations = text_block.get("translation") or text_block.get("translations") or []
        if isinstance(translations, list):
            for item in translations:
                text = item.get("text")
                if text:
                    return text.strip()
    return default


def _extract_routes(informed_entities: list[dict[str, Any]]) -> list[str]:
    routes: list[str] = []
    for entity in informed_entities:
        route = entity.get("routeId") or entity.get("route_id")
        if route and route not in routes:
            routes.append(route.upper())
    return routes


def _parse_alert_payload(payload: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for entity in _extract_entities(payload):
        alert = entity.get("alert") or {}
        informed_entities = alert.get("informedEntity") or alert.get("informed_entity") or []
        routes = _extract_routes(informed_entities)
        line = routes[0] if routes else ("bus" if mode == "bus" else "system")
        headline = _extract_text(alert.get("headerText") or alert.get("header_text"), f"{line} service alert")
        detail = _extract_text(
            alert.get("descriptionText") or alert.get("description_text"),
            "Service changes are active right now.",
        )
        parsed.append(
            {
                "line": line,
                "headline": headline,
                "detail": detail,
                "severity": "warning",
                "routes": routes,
            }
        )
    return parsed


def _filter_alerts(alerts: list[dict[str, Any]], requested_lines: list[str] | None) -> list[dict[str, Any]]:
    if not requested_lines:
        return alerts
    requested = {(line or "").upper() for line in requested_lines if line}
    filtered = []
    for alert in alerts:
        routes = {route.upper() for route in alert.get("routes", [])}
        line = (alert.get("line") or "").upper()
        if routes & requested or line in requested or line == "SYSTEM":
            filtered.append(alert)
    return filtered


def get_subway_alerts(lines: list[str] | None = None) -> dict[str, Any] | None:
    payload = _request_json(MTA_ALERT_FEEDS["subway_alerts"], "alerts:subway")
    if payload is None:
        return None

    alerts = _parse_alert_payload(payload, "subway")
    filtered_alerts = _filter_alerts(alerts, lines)
    line_feeds = []
    for line in lines or []:
        feed_info = get_line_feed(line)
        if feed_info is not None:
            line_feeds.append(feed_info)

    return {
        "alerts": filtered_alerts or alerts,
        "line_feeds": line_feeds,
        "source": "mta_json",
        "updated_at": time.time(),
    }


def get_bus_alerts(routes: list[str] | None = None) -> dict[str, Any] | None:
    payload = _request_json(MTA_ALERT_FEEDS["bus_alerts"], "alerts:bus")
    if payload is None:
        return None

    alerts = _parse_alert_payload(payload, "bus")
    if routes:
        requested = {(route or "").upper() for route in routes if route}
        alerts = [alert for alert in alerts if (alert.get("line") or "").upper() in requested or not alert.get("routes")]

    return {
        "alerts": alerts,
        "source": "mta_json",
        "updated_at": time.time(),
    }


def get_mta_snapshot(lines: list[str] | None = None, routes: list[str] | None = None) -> dict[str, Any]:
    subway = get_subway_alerts(lines)
    bus = get_bus_alerts(routes)
    subway_payload = subway or _fallback_alerts("subway")
    bus_payload = bus or _fallback_alerts("bus")

    return {
        "subway_alerts": subway_payload.get("alerts", []),
        "bus_alerts": bus_payload.get("alerts", []),
        "line_feeds": subway_payload.get("line_feeds", []),
        "source": "live" if subway is not None or bus is not None else "fallback",
    }


if __name__ == "__main__":
    print("Testing mta_service...")
    result = get_mta_snapshot(["A"])
    print(f"Result: {result}")
    print("mta_service OK" if result is not None else "mta_service returned None (using fallback)")
