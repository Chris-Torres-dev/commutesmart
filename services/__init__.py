from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)


def make_cache_key(*parts: Any) -> str:
    joined = "|".join(str(part).strip().lower() for part in parts if part is not None)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def cache_is_fresh(timestamp: float | None, duration: int) -> bool:
    return bool(timestamp) and (time.time() - timestamp) < duration


def safe_get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    timeout: int = 8,
) -> Any:
    response = requests.get(url, headers=headers, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()
