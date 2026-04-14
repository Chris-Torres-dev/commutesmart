from __future__ import annotations

import re
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from flask import template_rendered

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app
from models import db
from models.profile import Profile
from models.spend_log import SpendLog
from models.user import User
from routes.finance import get_week_start

SMOKE_TESTS = [
    "test_budget_add_endpoint",
    "test_budget_reset_endpoint",
    "test_budget_delete_endpoint",
    "test_finance_page_logged_out",
    "test_finance_weekly_data",
    "test_finance_monthly_data",
    "test_chat_specific_response",
    "test_chat_no_loop",
    "test_budget_bar_renders",
    "test_chart_canvas_renders",
]


@contextmanager
def captured_templates(app):
    recorded = []

    def record(sender, template, context, **extra):
        recorded.append((template, context))

    template_rendered.connect(record, app)
    try:
        yield recorded
    finally:
        template_rendered.disconnect(record, app)


class SmokeTestsV13(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "smoke_v13.db"
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

    def _extract_csrf_token(self, html: str, pattern: str = r'name="csrf_token" value="([^"]+)"') -> str:
        match = re.search(pattern, html)
        self.assertIsNotNone(match, "Expected csrf token in HTML")
        return match.group(1)

    def _create_user(self, email: str = "smoke@example.com") -> User:
        user = User(email=email, is_guest=False)
        user.set_password("testpass123")
        db.session.add(user)
        db.session.commit()
        return user

    def _login_user(self, email: str = "smoke@example.com", password: str = "testpass123") -> None:
        login_page = self.client.get("/login", base_url=self.base_url)
        csrf_token = self._extract_csrf_token(login_page.get_data(as_text=True))
        response = self.client.post(
            "/login",
            data={"email": email, "password": password, "csrf_token": csrf_token},
            headers={"Referer": f"{self.base_url}/login"},
            base_url=self.base_url,
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

    def _set_guest_session(self) -> None:
        with self.client.session_transaction() as session:
            session["guest_mode"] = True
            session["is_guest"] = True
            session["onboarding_data"] = {
                "home_address": "Brooklyn, NY",
                "school_name": "Hunter College",
                "weekly_budget": 34.0,
                "transport_modes": ["subway", "bike"],
                "days_per_week": 4,
            }
            session.modified = True

    @contextmanager
    def _dashboard_stub_context(self):
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
        finance_payload = {
            "budget": 34.0,
            "metrics": {"week": 0.0},
            "budget_status": {"percent": 0, "remaining": 34.0},
            "logs": [],
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
            patch("routes.dashboard.build_finance_payload", return_value=finance_payload),
            patch("routes.dashboard.get_recommendation", return_value=recommendation),
        ):
            yield

    def _get_dashboard_csrf(self) -> str:
        with self._dashboard_stub_context():
            response = self.client.get("/dashboard", base_url=self.base_url)
        html = response.get_data(as_text=True)
        return self._extract_csrf_token(html)

    def test_budget_add_endpoint(self):
        user = self._create_user("budget-add@example.com")
        db.session.add(Profile(user_id=user.id, weekly_budget=34.0, transport_modes=["subway"]))
        db.session.commit()
        self._login_user(user.email)
        csrf_token = self._get_dashboard_csrf()

        response = self.client.post(
            "/api/budget/add",
            json={"amount": 7.50},
            headers={"X-CSRFToken": csrf_token, "Referer": f"{self.base_url}/dashboard"},
            base_url=self.base_url,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SpendLog.query.filter_by(user_id=user.id).count(), 1)

    def test_budget_reset_endpoint(self):
        user = self._create_user("budget-reset@example.com")
        self._login_user(user.email)
        week_start = datetime.utcnow().date() - timedelta(days=datetime.utcnow().date().weekday())
        db.session.add(SpendLog(user_id=user.id, week_start_date=week_start, amount_spent=8.0, transport_mode="subway"))
        db.session.commit()
        csrf_token = self._get_dashboard_csrf()

        response = self.client.post(
            "/api/budget/reset",
            json={},
            headers={"X-CSRFToken": csrf_token, "Referer": f"{self.base_url}/dashboard"},
            base_url=self.base_url,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SpendLog.query.filter_by(user_id=user.id, week_start_date=week_start).count(), 0)

    def test_budget_delete_endpoint(self):
        user = self._create_user("budget-delete@example.com")
        self._login_user(user.email)
        older = SpendLog(user_id=user.id, week_start_date=get_week_start(), amount_spent=5.0, transport_mode="subway", created_at=datetime.utcnow() - timedelta(hours=1))
        newer = SpendLog(user_id=user.id, week_start_date=get_week_start(), amount_spent=9.0, transport_mode="subway", created_at=datetime.utcnow())
        db.session.add_all([older, newer])
        db.session.commit()
        csrf_token = self._get_dashboard_csrf()

        response = self.client.post(
            "/api/budget/delete-last",
            json={},
            headers={"X-CSRFToken": csrf_token, "Referer": f"{self.base_url}/dashboard"},
            base_url=self.base_url,
        )
        self.assertEqual(response.status_code, 200)
        amounts = [log.amount_spent for log in SpendLog.query.filter_by(user_id=user.id).all()]
        self.assertEqual(amounts, [5.0])

    def test_finance_page_logged_out(self):
        self._set_guest_session()
        response = self.client.get("/finance", base_url=self.base_url)
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Create an account to see your spending history here.", body)
        self.assertIn("Create an account to track your monthly spending trend.", body)

    def test_finance_weekly_data(self):
        user = self._create_user("finance-week@example.com")
        db.session.add(Profile(user_id=user.id, weekly_budget=34.0, transport_modes=["subway"]))
        db.session.add(SpendLog(user_id=user.id, week_start_date=get_week_start(), amount_spent=12.0, transport_mode="subway"))
        db.session.commit()
        self._login_user(user.email)

        with captured_templates(self.app) as templates:
            response = self.client.get("/finance", base_url=self.base_url)

        self.assertEqual(response.status_code, 200)
        template, context = templates[-1]
        self.assertEqual(len(context["weekly_data"]), 8)

    def test_finance_monthly_data(self):
        user = self._create_user("finance-month@example.com")
        db.session.add(Profile(user_id=user.id, weekly_budget=34.0, transport_modes=["subway"]))
        db.session.add(SpendLog(user_id=user.id, week_start_date=get_week_start(), amount_spent=15.0, transport_mode="subway", created_at=datetime.utcnow()))
        db.session.commit()
        self._login_user(user.email)

        with captured_templates(self.app) as templates:
            response = self.client.get("/finance", base_url=self.base_url)

        self.assertEqual(response.status_code, 200)
        template, context = templates[-1]
        self.assertEqual(len(context["monthly_data"]), 6)

    def test_chat_specific_response(self):
        self._set_guest_session()
        csrf_token = self._get_dashboard_csrf()
        response = self.client.post(
            "/api/chat",
            json={"message": "What is the fastest route?"},
            headers={"X-CSRFToken": csrf_token, "Referer": f"{self.base_url}/dashboard"},
            base_url=self.base_url,
        )
        reply = response.get_json()["reply"]
        self.assertEqual(response.status_code, 200)
        self.assertIn("fastest", reply.lower())

    def test_chat_no_loop(self):
        self._set_guest_session()
        csrf_token = self._get_dashboard_csrf()
        response_one = self.client.post(
            "/api/chat",
            json={"message": "What is the fastest route?"},
            headers={"X-CSRFToken": csrf_token, "Referer": f"{self.base_url}/dashboard"},
            base_url=self.base_url,
        )
        response_two = self.client.post(
            "/api/chat",
            json={"message": "What is the cheapest route?"},
            headers={"X-CSRFToken": csrf_token, "Referer": f"{self.base_url}/dashboard"},
            base_url=self.base_url,
        )
        self.assertNotEqual(response_one.get_json()["reply"], response_two.get_json()["reply"])

    def test_budget_bar_renders(self):
        self._set_guest_session()
        with self._dashboard_stub_context():
            response = self.client.get("/dashboard", base_url=self.base_url)
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="budget-bar-fill"', body)
        self.assertIn('id="spend-input"', body)

    def test_chart_canvas_renders(self):
        user = self._create_user("finance-canvas@example.com")
        db.session.add(Profile(user_id=user.id, weekly_budget=34.0, transport_modes=["subway"]))
        db.session.commit()
        self._login_user(user.email)
        response = self.client.get("/finance", base_url=self.base_url)
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="weeklyChart"', body)
        self.assertIn('id="monthlyChart"', body)


def main():
    suite = unittest.TestSuite()
    for test_name in SMOKE_TESTS:
        suite.addTest(SmokeTestsV13(test_name))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"Smoke tests summary: {passed}/{result.testsRun} passed")
    if result.wasSuccessful():
        print("All smoke tests passed")


if __name__ == "__main__":
    main()
