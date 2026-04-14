from __future__ import annotations

import logging
import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger(__name__)


def _get_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if value in (None, ""):
        logger.warning("WARNING: %s not set - using fallback mode", name)
    return value


class Config:
    SECRET_KEY = _get_env("FLASK_SECRET_KEY", "commutesmart-dev-secret")
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{(BASE_DIR / 'commutesmart.db').as_posix()}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEBUG = os.getenv("FLASK_ENV", "development") == "development"
    GOOGLE_MAPS_API_KEY = _get_env("GOOGLE_MAPS_API_KEY")
    NEWSAPI_KEY = _get_env("NEWSAPI_KEY")
    COLLECT_API_KEY = _get_env("COLLECT_API_KEY")
    OPENAI_API_KEY = _get_env("OPENAI_API_KEY")
    SESSION_COOKIE_NAME = "commutesmart_session"
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(seconds=86400)

    # MTA fares (as of 2025)
    OMNY_PER_RIDE = 2.90
    OMNY_WEEKLY_CAP = 34.00
    MTA_30DAY_UNLIMITED = 132.00
    FAIR_FARES_PER_RIDE = 1.45

    # Citi Bike pricing
    CITIBIKE_MONTHLY = 17.99
    CITIBIKE_DAY_PASS = 15.00
    CITIBIKE_SINGLE_RIDE = 4.49

    # NYC tolls (2025 rates)
    TOLLS = {
        "holland_tunnel": 17.00,
        "lincoln_tunnel": 17.00,
        "george_washington": 17.00,
        "battery_tunnel": 10.17,
        "midtown_tunnel": 10.17,
        "congestion_pricing_enter_manhattan": 9.00,
        "verrazano": 22.00,
        "goethals": 17.00,
        "rba": 17.00,
    }

    DEFAULT_GAS_PRICE_NYC = 3.45
    DEFAULT_MPG = 28.0
    PARKING_ESTIMATES = {
        "manhattan": 40.00,
        "brooklyn": 15.00,
        "queens": 12.00,
        "bronx": 10.00,
        "staten_island": 8.00,
    }

    DAILY_AI_CALL_LIMIT = 50
    MAPS_CACHE_DURATION = 1800
    MTA_SUBWAY_CACHE_DURATION = 60
    MTA_BUS_CACHE_DURATION = 60
    CITIBIKE_CACHE_DURATION = 30
    NEWS_CACHE_DURATION = 3600
    GAS_CACHE_DURATION = 21600
    AI_CACHE_DURATION = 600

    DEFAULT_SCHOOLS = [
        {
            "name": "The City College of New York",
            "address": "160 Convent Ave, New York, NY 10031",
        },
        {
            "name": "Brooklyn College",
            "address": "2900 Bedford Ave, Brooklyn, NY 11210",
        },
        {
            "name": "Queens College",
            "address": "65-30 Kissena Blvd, Queens, NY 11367",
        },
        {
            "name": "Baruch College",
            "address": "55 Lexington Ave, New York, NY 10010",
        },
        {
            "name": "Hunter College",
            "address": "695 Park Ave, New York, NY 10065",
        },
        {
            "name": "City Tech",
            "address": "300 Jay St, Brooklyn, NY 11201",
        },
        {
            "name": "Lehman College",
            "address": "250 Bedford Park Blvd W, Bronx, NY 10468",
        },
        {
            "name": "College of Staten Island",
            "address": "2800 Victory Blvd, Staten Island, NY 10314",
        },
        {
            "name": "Medgar Evers College",
            "address": "1650 Bedford Ave, Brooklyn, NY 11225",
        },
        {
            "name": "York College",
            "address": "94-20 Guy R Brewer Blvd, Jamaica, NY 11451",
        },
    ]

    FALLBACK_NEWS = [
        {
            "title": "Fair Fares NYC",
            "summary": "Half-price subway and bus fares for eligible New Yorkers.",
            "url": "https://www.nyc.gov/site/fairfares/index.page",
            "published_at": "Always available",
        },
        {
            "title": "CUNY ASAP Transit Support",
            "summary": "Academic support programs that can include MetroCard help for eligible students.",
            "url": "https://www.cuny.edu/about/administration/offices/undergraduate-studies/asap/",
            "published_at": "Program resource",
        },
        {
            "title": "NYC Commuter Benefits",
            "summary": "Pre-tax commuter savings options for students who also work.",
            "url": "https://www.nyc.gov/site/olr/commuter-benefits/commuter-benefits.page",
            "published_at": "Program resource",
        },
    ]


def missing_env_keys() -> list[str]:
    keys = [
        "FLASK_SECRET_KEY",
        "GOOGLE_MAPS_API_KEY",
        "NEWSAPI_KEY",
        "COLLECT_API_KEY",
        "OPENAI_API_KEY",
    ]
    return [key for key in keys if not os.getenv(key)]
