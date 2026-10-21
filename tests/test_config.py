import logging
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from bot import SafeFormatter
from access import DEFAULT_ACCESS_PATH
from config import ConfigError, load_config


def environment():
    return {
        "BOT_TOKEN": "123456:synthetic_test_token",
        "BITRIX_WEBHOOK_URL": "https://example.invalid/rest/1/synthetic_test_key/",
        "MISSED_CALL_STAGE_ID": "TEST_STAGE",
        "MANAGER_1_NAME": "Иван", "MANAGER_2_NAME": "Анна", "MANAGER_3_NAME": "Сергей",
        "ALLOWED_TELEGRAM_IDS": "123, 456,123",
    }


class ConfigTests(unittest.TestCase):
    def test_distribution_capabilities_are_explicit_and_ids_validated(self):
        env = environment()
        env["ADMIN_TELEGRAM_IDS"] = "8306778724"
        config = self.load(env)
        self.assertEqual(config.distribution_confirmer_ids, frozenset())
        self.assertIsNone(config.distribution_queue_path)
        env.update(DISTRIBUTION_CONFIRMER_IDS="8306778724", PLANNER_ACTIVE_MANAGER_IDS="8306778724,7939114214", MANAGER_1_TELEGRAM_ID="8306778724", MANAGER_2_TELEGRAM_ID="7939114214", DISTRIBUTION_QUEUE_PATH="test-queue.db")
        config = self.load(env)
        self.assertEqual(config.distribution_confirmer_ids, frozenset({8306778724}))
        self.assertEqual(config.manager_telegram_ids, (8306778724, 7939114214, 0))
        env["MANAGER_3_TELEGRAM_ID"] = "8306778724"
        with self.assertRaises(ConfigError):
            self.load(env)
        env["MANAGER_3_TELEGRAM_ID"] = "invalid"
        with self.assertRaises(ConfigError):
            self.load(env)

    def load(self, env):
        with patch.dict(os.environ, env, clear=True), patch("config.load_dotenv"):
            return load_config(Path("unused.env"))

    def test_valid_default_timezone_and_no_secrets_in_repr(self):
        config = self.load(environment())
        self.assertEqual(config.timezone.key, "Europe/Moscow")
        self.assertEqual(config.allowed_telegram_ids, frozenset({123, 456}))
        self.assertEqual(config.admin_telegram_ids, frozenset())
        self.assertEqual(config.access_db_path, DEFAULT_ACCESS_PATH)
        self.assertNotIn(config.bot_token, repr(config))
        self.assertNotIn(config.bitrix_webhook_url, repr(config))

    def test_missing_values(self):
        with self.assertRaises(ConfigError) as caught:
            self.load({})
        self.assertIn("BOT_TOKEN", str(caught.exception))
        self.assertIn("MISSED_CALL_STAGE_ID", str(caught.exception))

    def test_invalid_values_are_not_echoed(self):
        for key, value in [
            ("BOT_TOKEN", "secret-invalid"), ("BITRIX_WEBHOOK_URL", "https://secret.invalid/bad"),
            ("BITRIX_WEBHOOK_URL", "http://example.invalid/rest/1/key/"),
            ("ALLOWED_TELEGRAM_IDS", "123,garbage"), ("ALLOWED_TELEGRAM_IDS", "123,"),
            ("ALLOWED_TELEGRAM_IDS", "-123"), ("TIMEZONE", "Invalid/Zone"),
            ("MANAGER_1_NAME", "Анна"),
            ("ADMIN_TELEGRAM_IDS", "123,garbage"), ("ADMIN_TELEGRAM_IDS", "123,"),
            ("ADMIN_TELEGRAM_IDS", "0"), ("ADMIN_TELEGRAM_IDS", "-123"),
            ("ADMIN_TELEGRAM_IDS", str(2**63)), ("ALLOWED_TELEGRAM_IDS", str(2**63)),
        ]:
            env = environment() | {key: value}
            with self.subTest(key=key, value=value), self.assertRaises(ConfigError) as caught:
                self.load(env)
            self.assertNotIn(value, str(caught.exception))

    def test_multiple_admins_and_empty_seed(self):
        config = self.load(environment() | {"ADMIN_TELEGRAM_IDS": "777, 888,777", "ALLOWED_TELEGRAM_IDS": ""})
        self.assertEqual(config.admin_telegram_ids, frozenset({777, 888}))
        self.assertEqual(config.allowed_telegram_ids, frozenset())

    def test_custom_database_path(self):
        config = self.load(environment() | {"ACCESS_DB_PATH": "/data/access.db"})
        self.assertEqual(config.access_db_path, Path("/data/access.db"))
        self.assertEqual(self.load(environment() | {"ACCESS_DB_PATH": " "}).access_db_path, DEFAULT_ACCESS_PATH)

    def test_stages_and_manager_rename(self):
        config = self.load(environment() | {"MANAGER_3_NAME": "Женя", "INCONVENIENT_STAGE_ID": "PROCESSED",
                                            "UNPROCESSED_STAGE_ID": "NEW"})
        self.assertEqual(config.manager_names[-1], "Евгений")
        self.assertEqual(config.stages[1:], (("Неудобно говорить", "PROCESSED"), ("Не обработан", "NEW")))

    def test_log_redaction(self):
        config = self.load(environment())
        record = logging.LogRecord("test", logging.ERROR, __file__, 1,
                                   "%s %s", (config.bot_token, config.bitrix_webhook_url + "crm.item.list"), None)
        text = SafeFormatter(config).format(record)
        self.assertNotIn(config.bot_token, text)
        self.assertNotIn("synthetic_test_key", text)
        self.assertNotIn("https://", text)

    def test_mini_app_is_optional_and_requires_https(self):
        self.assertEqual(self.load(environment()).mini_app_url, "")
        self.assertEqual(self.load(environment() | {"MINI_APP_URL": "https://planner.example.com/"}).mini_app_url,
                         "https://planner.example.com/")
        for url in ("http://planner.example.com/", "javascript:alert(1)", "https://user:pass@planner.example.com/"):
            with self.subTest(url=url), self.assertRaises(ConfigError):
                self.load(environment() | {"MINI_APP_URL": url})
