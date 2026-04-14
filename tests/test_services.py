from __future__ import annotations

import unittest
from unittest.mock import patch
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Config
from services.ai_service import get_recommendation
from services.car_service import calculate_car_cost
from services.citibike_service import get_station_status
from services.maps_service import get_route
from services.mta_service import _mta_cache, get_feed_key_for_line, get_line_feed, get_mta_snapshot, get_subway_alerts
from services.news_service import get_news


class ServiceTests(unittest.TestCase):
    def setUp(self):
        _mta_cache.clear()

    @patch("services.mta_service.requests.get")
    def test_mta_service_fallback(self, mock_get):
        mock_get.side_effect = Exception("feed down")
        self.assertIsNone(get_subway_alerts())
        snapshot = get_mta_snapshot(["A"])
        self.assertEqual(snapshot["source"], "fallback")
        self.assertTrue(snapshot["subway_alerts"])

    @patch("services.mta_service.requests.get")
    def test_mta_service_parses_subway_alerts(self, mock_get):
        class FakeResponse:
            content = b"fake-feed"

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "entity": [
                        {
                            "alert": {
                                "informedEntity": [{"routeId": "A"}],
                                "headerText": {"translation": [{"text": "A delays"}]},
                                "descriptionText": {"translation": [{"text": "Signal trouble"}]},
                            }
                        }
                    ]
                }

        mock_get.return_value = FakeResponse()
        result = get_subway_alerts(["A"])
        self.assertEqual(result["source"], "mta_json")
        self.assertEqual(result["alerts"][0]["line"], "A")

    @patch("services.mta_service.requests.get")
    def test_mta_line_feed_detection(self, mock_get):
        class FakeResponse:
            content = b"fake-feed"

            def raise_for_status(self):
                return None

        mock_get.return_value = FakeResponse()
        self.assertEqual(get_feed_key_for_line("Q"), "NQRW")
        result = get_line_feed("Q")
        self.assertEqual(result["feed_key"], "NQRW")
        self.assertEqual(result["bytes"], len(b"fake-feed"))

    def test_maps_service_fallback(self):
        result = get_route("Brooklyn, NY", "Baruch College, New York, NY", "transit")
        self.assertIn("duration_seconds", result)
        self.assertIn("distance_meters", result)

    def test_car_service_fallback(self):
        result = calculate_car_cost("Brooklyn, NY", "Baruch College, New York, NY", days_per_week=4)
        self.assertAlmostEqual(result["gas_price"], Config.DEFAULT_GAS_PRICE_NYC)
        self.assertIn("total", result)

    def test_ai_service_fallback(self):
        result = get_recommendation(
            {"weekly_budget": 20, "transport_modes": ["subway"], "days_per_week": 4, "trips_per_day": 2},
            [{"plan_name": "OMNY weekly cap", "mode": "subway", "weekly_cost": 34}],
        )
        self.assertIn("best_plan", result)

    def test_news_service_fallback(self):
        result = get_news()
        self.assertTrue(len(result) >= 3)

    @patch("services.citibike_service.safe_get_json")
    def test_citibike_service_parses_payload(self, mock_safe_get_json):
        mock_safe_get_json.return_value = {
            "data": {
                "stations": [
                    {"station_id": "1", "num_bikes_available": 3},
                    {"station_id": "2", "num_bikes_available": 9},
                ]
            }
        }
        result = get_station_status(limit=1)
        self.assertEqual(result["stations"][0]["station_id"], "2")


if __name__ == "__main__":
    unittest.main()
