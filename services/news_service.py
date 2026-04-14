from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from config import Config
from services import safe_get_json

logger = logging.getLogger(__name__)

_news_cache: list[dict[str, Any]] | None = None
_news_last_fetched: float | None = None


def _fallback_news() -> list[dict[str, Any]]:
    return Config.FALLBACK_NEWS


def format_news_date(iso_string: str | None) -> str:
    try:
        dt = datetime.strptime(str(iso_string), "%Y-%m-%dT%H:%M:%SZ")
        return dt.strftime("%b %d, %Y")
    except (TypeError, ValueError):
        return ""


def get_news() -> list[dict[str, Any]]:
    global _news_cache, _news_last_fetched

    if _news_cache and _news_last_fetched and (time.time() - _news_last_fetched) < Config.NEWS_CACHE_DURATION:
        return _news_cache

    if not Config.NEWSAPI_KEY:
        _news_cache = _fallback_news()
        _news_last_fetched = time.time()
        return _news_cache

    params = {
        "q": "NYC transit student discount OR Fair Fares OR MTA student OR CUNY commute",
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 5,
        "apiKey": Config.NEWSAPI_KEY,
    }
    try:
        payload = safe_get_json("https://newsapi.org/v2/everything", params=params, timeout=8)
        articles = []
        for article in payload.get("articles", [])[:5]:
            articles.append(
                {
                    "title": article.get("title"),
                    "summary": article.get("description") or "Transit support update for NYC students.",
                    "url": article.get("url"),
                    "published_at": article.get("publishedAt"),
                }
            )
        _news_cache = articles or _fallback_news()
        _news_last_fetched = time.time()
        return _news_cache
    except Exception as exc:  # pragma: no cover - network-dependent
        logger.warning("NewsAPI fetch failed: %s", exc)
        _news_cache = _fallback_news()
        _news_last_fetched = time.time()
        return _news_cache


if __name__ == "__main__":
    print("Testing news_service...")
    result = get_news()
    print(f"Result: {result}")
    print("✅ news_service OK" if result is not None else "⚠ news_service returned None (check API key)")
