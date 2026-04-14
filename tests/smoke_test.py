from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app
from models import db
from models.user import User
from services.mta_service import MTA_FEEDS

SMOKE_TESTS_V1_2 = [
    "test_guest_can_access_plan",
    "test_guest_can_access_finance",
    "test_guest_can_access_onboarding",
    "test_mta_feeds_reachable",
    "test_security_headers_present",
    "test_login_generic_error_message",
    "test_yellow_buttons_readable",
    "test_404_page_loads",
    "test_news_date_formatted",
    "test_guest_budget_empty_state",
]


class SmokeTestsV12(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "smoke_v12.db"
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "smoke-secret",
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.db_path.as_posix()}",
            }
        )
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()
        self.base_url = "https://localhost"

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        for engine in db.engines.values():
            engine.dispose()
        self.app_context.pop()
        self.temp_dir.cleanup()

    def _set_guest_session(self):
        with self.client.session_transaction() as session:
            session["guest_mode"] = True
            session["is_guest"] = True
            session["onboarding_data"] = {}
            session.modified = True

    def _extract_csrf_token(self, html: str) -> str:
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        self.assertIsNotNone(match, "Expected csrf_token hidden input in form HTML")
        return match.group(1)

    def test_guest_can_access_plan(self):
        self._set_guest_session()
        plans = [
            {
                "plan_name": "Pay-per-ride",
                "mode": "subway",
                "weekly_cost": 29.0,
                "duration_minutes": 42,
                "best_for": "Lighter commute weeks",
                "summary": "Best when your class schedule changes often.",
                "icon": "fa-train-subway",
                "estimated": False,
                "distance_miles": 7.2,
            }
        ]
        recommendation = {
            "best_plan": "Pay-per-ride",
            "reason": "Best balance of speed and cost.",
            "tip": "Track your weekly spend and upgrade only if rides increase.",
            "savings_message": "You stay under budget this week.",
        }
        with (
            patch("routes.planner.build_commute_plans", return_value=plans),
            patch(
                "routes.planner.get_mta_snapshot",
                return_value={"subway_alerts": [], "bus_alerts": [], "line_feeds": [], "source": "fallback"},
            ),
            patch("routes.planner.get_station_status", return_value=None),
            patch("routes.planner.get_recommendation", return_value=recommendation),
        ):
            response = self.client.get("/plan", base_url=self.base_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Compare your commute options", response.get_data(as_text=True))

    def test_guest_can_access_finance(self):
        self._set_guest_session()
        response = self.client.get("/finance", base_url=self.base_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Keep your commute spending in bounds", response.get_data(as_text=True))

    def test_guest_can_access_onboarding(self):
        self._set_guest_session()
        response = self.client.get("/onboarding/1", base_url=self.base_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Next step", response.get_data(as_text=True))

    def test_mta_feeds_reachable(self):
        response = requests.get(MTA_FEEDS["ACE"], timeout=15)
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.content), 0)

    def test_security_headers_present(self):
        response = self.client.get("/", base_url=self.base_url)
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIsNotNone(response.headers.get("Content-Security-Policy"))
        self.assertIsNotNone(response.headers.get("Strict-Transport-Security"))

    def test_login_generic_error_message(self):
        user = User(email="student@example.com", is_guest=False)
        user.set_password("testpass123")
        db.session.add(user)
        db.session.commit()

        login_page = self.client.get("/login", base_url=self.base_url)
        csrf_token = self._extract_csrf_token(login_page.get_data(as_text=True))
        response = self.client.post(
            "/login",
            data={
                "email": "student@example.com",
                "password": "wrongpass123",
                "csrf_token": csrf_token,
            },
            headers={"Referer": f"{self.base_url}/login"},
            base_url=self.base_url,
            follow_redirects=True,
        )
        body = response.get_data(as_text=True)
        self.assertIn("Incorrect email or password", body)
        self.assertNotIn("Email not found", body)
        self.assertNotIn("Wrong password", body)

    def test_yellow_buttons_readable(self):
        components_css = (ROOT / "static" / "css" / "components.css").read_text(encoding="utf-8")
        self.assertIn(".btn-primary {", components_css)
        self.assertIn("color: #060E1A;", components_css)
        self.assertIn(".badge-yellow {", components_css)
        self.assertIn("background: var(--yellow);", components_css)

    def test_404_page_loads(self):
        response = self.client.get("/not-a-real-page", base_url=self.base_url)
        self.assertEqual(response.status_code, 404)
        self.assertIn("This stop doesn't exist.", response.get_data(as_text=True))

    def test_news_date_formatted(self):
        self._set_guest_session()
        plans = [
            {
                "plan_name": "Pay-per-ride",
                "weekly_cost": 29.0,
                "duration_minutes": 42,
                "summary": "Best when your class schedule changes often.",
                "best_for": "Lighter commute weeks",
            }
        ]
        finance_payload = {"budget": 34.0, "metrics": {"week": 0.0}, "budget_status": {"percent": 0, "remaining": 34.0}}
        recommendation = {"best_plan": "Pay-per-ride", "reason": "Best for a light class week.", "tip": "Start with transit and save the rest."}
        news_cards = [
            {
                "title": "Transit grant expanded",
                "summary": "Support update.",
                "url": "https://example.com",
                "published_at": "2026-04-02T14:30:00Z",
            }
        ]

        with (
            patch("routes.dashboard.build_commute_plans", return_value=plans),
            patch(
                "routes.dashboard.get_mta_snapshot",
                return_value={"subway_alerts": [], "bus_alerts": [], "line_feeds": [], "source": "fallback"},
            ),
            patch("routes.dashboard.build_finance_payload", return_value=finance_payload),
            patch("routes.dashboard.get_recommendation", return_value=recommendation),
            patch("routes.dashboard.get_news", return_value=news_cards),
        ):
            response = self.client.get("/dashboard", base_url=self.base_url)

        body = response.get_data(as_text=True)
        self.assertIn("Apr 02, 2026", body)
        self.assertNotIn("2026-04-02T14:30:00Z", body)

    def test_guest_budget_empty_state(self):
        self._set_guest_session()
        plans = [
            {
                "plan_name": "Pay-per-ride",
                "weekly_cost": 29.0,
                "duration_minutes": 42,
                "summary": "Best when your class schedule changes often.",
                "best_for": "Lighter commute weeks",
            }
        ]
        finance_payload = {"budget": 34.0, "metrics": {"week": 0.0}, "budget_status": {"percent": 0, "remaining": 34.0}}
        recommendation = {"best_plan": "Pay-per-ride", "reason": "Best for a light class week.", "tip": "Start with transit and save the rest."}

        with (
            patch("routes.dashboard.build_commute_plans", return_value=plans),
            patch(
                "routes.dashboard.get_mta_snapshot",
                return_value={"subway_alerts": [], "bus_alerts": [], "line_feeds": [], "source": "fallback"},
            ),
            patch("routes.dashboard.build_finance_payload", return_value=finance_payload),
            patch("routes.dashboard.get_recommendation", return_value=recommendation),
            patch("routes.dashboard.get_news", return_value=[]),
        ):
            response = self.client.get("/dashboard", base_url=self.base_url)

        body = response.get_data(as_text=True)
        self.assertIn("Track your weekly commute budget", body)
        self.assertIn("Start tracking", body)
        self.assertNotIn("of $34 this week", body)


def main():
    suite = unittest.TestSuite()
    for test_name in SMOKE_TESTS_V1_2:
        suite.addTest(SmokeTestsV12(test_name))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"Smoke tests summary: {passed}/{result.testsRun} passed")
    if result.wasSuccessful():
        print("All smoke tests passed")


if __name__ == "__main__":
    main()
