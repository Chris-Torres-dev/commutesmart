from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app
from models import db

SMOKE_TESTS_V2 = [
    "test_health_endpoint",
    "test_rate_limit_login",
    "test_csrf_on_signup",
    "test_weak_password_rejected",
    "test_404_page",
    "test_gunicorn_starts",
    "test_mta_no_key_needed",
    "test_robots_txt",
    "test_guest_sees_plan_prompt",
    "test_loading_state_on_plan",
]


class SmokeTestsV2(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "smoke_v2.db"
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

    def _extract_csrf_token(self, html: str) -> str:
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        self.assertIsNotNone(match, "Expected csrf_token hidden input in form HTML")
        return match.group(1)

    def _set_guest_session(self):
        with self.client.session_transaction() as session:
            session["guest_mode"] = True
            session["onboarding_data"] = {}
            session.modified = True

    def test_health_endpoint(self):
        response = self.client.get("/health", base_url=self.base_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_rate_limit_login(self):
        login_page = self.client.get("/login", base_url=self.base_url)
        csrf_token = self._extract_csrf_token(login_page.get_data(as_text=True))

        statuses = []
        for _ in range(11):
            response = self.client.post(
                "/login",
                data={
                    "email": "nobody@example.com",
                    "password": "badpass123",
                    "csrf_token": csrf_token,
                },
                headers={"Referer": f"{self.base_url}/login"},
                base_url=self.base_url,
            )
            statuses.append(response.status_code)

        self.assertEqual(statuses[-1], 429)
        self.assertIn("faster than the A train", response.get_data(as_text=True))

    def test_csrf_on_signup(self):
        response = self.client.get("/signup", base_url=self.base_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="csrf_token"', response.get_data(as_text=True))

    def test_weak_password_rejected(self):
        signup_page = self.client.get("/signup", base_url=self.base_url)
        csrf_token = self._extract_csrf_token(signup_page.get_data(as_text=True))

        response = self.client.post(
            "/signup",
            data={
                "email": "weak@example.com",
                "password": "weak",
                "confirm_password": "weak",
                "csrf_token": csrf_token,
            },
            headers={"Referer": f"{self.base_url}/signup"},
            base_url=self.base_url,
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Password must be at least 8 characters and contain a number",
            response.get_data(as_text=True),
        )

    def test_404_page(self):
        response = self.client.get("/no-such-route", base_url=self.base_url)
        self.assertEqual(response.status_code, 404)
        self.assertIn(
            "This stop doesn't exist. Let's get you back on track.",
            response.get_data(as_text=True),
        )

    def test_gunicorn_starts(self):
        procfile = (ROOT / "Procfile").read_text(encoding="utf-8").strip()
        render_yaml = (ROOT / "render.yaml").read_text(encoding="utf-8")
        expected = "gunicorn app:app --bind 0.0.0.0:$PORT --workers 2"

        self.assertEqual(procfile, f"web: {expected}")
        self.assertIn(expected, render_yaml)

        if os.name == "nt":
            from app import app

            self.assertIsNotNone(app)
        else:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "gunicorn.app.wsgiapp",
                    "app:app",
                    "--check-config",
                    "--bind",
                    "127.0.0.1:5001",
                    "--workers",
                    "1",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

    def test_mta_no_key_needed(self):
        env = os.environ.copy()
        env.pop("MTA_API_KEY", None)
        result = subprocess.run(
            [sys.executable, "services/mta_service.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        self.assertIn("mta_service OK", result.stdout)

    def test_robots_txt(self):
        response = self.client.get("/robots.txt", base_url=self.base_url)
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Disallow: /api/", body)
        self.assertIn("Allow: /plan", body)

    def test_guest_sees_plan_prompt(self):
        self._set_guest_session()
        plans = [
            {
                "plan_name": "Pay-per-ride",
                "weekly_cost": 29.0,
                "duration_minutes": 42,
                "summary": "Best when your class schedule changes often.",
                "best_for": "Lighter commute weeks",
            },
            {
                "plan_name": "OMNY weekly cap",
                "weekly_cost": 34.0,
                "duration_minutes": 40,
                "summary": "Locks in transit spend once your rides stack up.",
                "best_for": "Frequent riders",
            },
        ]
        finance = {
            "budget": 34.0,
            "metrics": {"week": 0.0},
            "budget_status": {"percent": 0, "remaining": 34.0},
        }
        recommendation = {
            "best_plan": "Pay-per-ride",
            "reason": "Best for a light class week.",
            "tip": "Start with transit and save the rest.",
        }

        with (
            patch("routes.dashboard.build_commute_plans", return_value=plans),
            patch(
                "routes.dashboard.get_mta_snapshot",
                return_value={"subway_alerts": [], "bus_alerts": [], "line_feeds": [], "source": "fallback"},
            ),
            patch("routes.dashboard.get_news", return_value=[]),
            patch("routes.dashboard.build_finance_payload", return_value=finance),
            patch("routes.dashboard.get_recommendation", return_value=recommendation),
        ):
            response = self.client.get("/dashboard", base_url=self.base_url)

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Where do you commute from?", body)
        self.assertIn("Find my commute plan", body)

    def test_loading_state_on_plan(self):
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

        planner_js = (ROOT / "static" / "js" / "planner.js").read_text(encoding="utf-8")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="loading"', body)
        self.assertIn("Checking MTA, Citi Bike, and your budget...", body)
        self.assertIn("Finding your best plan...", planner_js)


def main():
    suite = unittest.TestSuite()
    for test_name in SMOKE_TESTS_V2:
        suite.addTest(SmokeTestsV2(test_name))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"Smoke tests summary: {passed}/{result.testsRun} passed")
    if result.wasSuccessful():
        print("All smoke tests passed")


if __name__ == "__main__":
    main()
