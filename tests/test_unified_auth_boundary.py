"""Unified-auth planning must not make LeadFlow cookies Telegram auth proofs."""
import unittest

from tests import test_planner as baseline


class TelegramBoundaryTests(unittest.TestCase):
    setUp = baseline.PlannerTests.setUp
    call = baseline.PlannerTests.call

    def test_leadflow_cookie_cannot_replace_telegram_hmac(self):
        self.client.cookies.set("access_token", "synthetic-leadflow-cookie-not-a-telegram-proof")
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.assertEqual(self.client.get("/api/plans").status_code, 401)
        self.assertEqual(self.client.get("/api/me?role=supervisor&employee_id=3").status_code, 401)

    def test_cookie_does_not_elevate_a_valid_telegram_manager(self):
        self.client.cookies.set("access_token", "synthetic-supervisor-cookie")
        self.assertEqual(self.call("GET", "/me").json()["user"]["role"], "manager")
        self.assertEqual(self.call("GET", "/employees").status_code, 403)
