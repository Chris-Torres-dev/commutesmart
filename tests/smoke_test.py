from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

from sqlalchemy import inspect

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app import create_app
from models import db
from models.user import User
from services.mta_service import get_subway_alerts

# SMOKE TEST RULES:
# 1. Run max 10 tests per session before stopping to evaluate
# 2. After 10 tests: print summary of pass/fail
# 3. If any test fails: identify root cause, fix it, then re-run that specific test only
# 4. Do NOT re-run all 10 after fixing one - only re-run the failed test(s)
# 5. Only run full suite again after all individual failures are resolved

SMOKE_TESTS = [
    "test_app_starts",
    "test_db_creates",
    "test_landing_page_loads",
    "test_signup_flow",
    "test_login_flow",
    "test_guest_mode",
    "test_onboarding_skip",
    "test_plan_route_loads",
    "test_finance_loads",
    "test_mta_fallback",
]


class SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "smoke_commutesmart.db"
        cls.app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{cls.db_path.as_posix()}",
                "SECRET_KEY": "smoke-secret",
            }
        )
        cls.app_context = cls.app.app_context()
        cls.app_context.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.drop_all()
        for engine in db.engines.values():
            engine.dispose()
        cls.app_context.pop()
        cls.temp_dir.cleanup()

    def setUp(self):
        db.session.remove()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session.clear()
        User.query.delete()
        db.session.commit()

    def _signup_user(self, email: str = "smoke@example.com", password: str = "testpass123"):
        return self.client.post(
            "/signup",
            data={"email": email, "password": password, "confirm_password": password},
            follow_redirects=False,
        )

    def test_app_starts(self):
        self.assertIsNotNone(self.app)

    def test_db_creates(self):
        tables = inspect(db.engine).get_table_names()
        self.assertTrue({"users", "profiles", "spend_log", "saved_plans"}.issubset(set(tables)))

    def test_landing_page_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"CommuteSmart", response.data)

    def test_signup_flow(self):
        response = self._signup_user()
        self.assertEqual(response.status_code, 302)
        self.assertIn("/onboarding/1", response.headers["Location"])
        self.assertIsNotNone(User.query.filter_by(email="smoke@example.com").first())

    def test_login_flow(self):
        user = User(email="smoke@example.com", is_guest=False)
        user.set_password("testpass123")
        db.session.add(user)
        db.session.commit()
        response = self.client.post(
            "/login",
            data={"email": "smoke@example.com", "password": "testpass123"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Here's your best shot", response.data)

    def test_guest_mode(self):
        guest_db_path = Path(self.temp_dir.name) / "guest_mode.db"
        guest_app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{guest_db_path.as_posix()}",
                "SECRET_KEY": "guest-secret",
            }
        )
        guest_client = guest_app.test_client()
        response = guest_client.get("/guest", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"guest mode", response.data.lower())
        with guest_app.app_context():
            db.session.remove()
            db.drop_all()
            for engine in db.engines.values():
                engine.dispose()

    def test_onboarding_skip(self):
        self.client.get("/guest")
        response = self.client.get("/onboarding/skip", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Default commute setup loaded", response.data)

    def test_plan_route_loads(self):
        self.client.get("/guest")
        response = self.client.get("/plan", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Compare your commute options", response.data)

    def test_finance_loads(self):
        self._signup_user()
        response = self.client.get("/finance", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Keep your commute spending in bounds", response.data)

    def test_mta_fallback(self):
        result = get_subway_alerts()
        self.assertEqual(result.get("source"), "fallback")
        self.assertTrue(result.get("alerts"))


def main():
    suite = unittest.TestSuite()
    for test_name in SMOKE_TESTS:
        suite.addTest(SmokeTests(test_name))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"Smoke tests summary: {passed}/{result.testsRun} passed")
    if result.wasSuccessful():
        print("✅ All smoke tests passed - app is ready")


if __name__ == "__main__":
    main()
