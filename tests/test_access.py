import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from access import AccessStore, parse_telegram_id


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "test_access.db"
        self.access = AccessStore(self.path)
        self.access.initialize()

    def test_add_and_check_user(self):
        self.assertFalse(self.access.contains(123))
        self.assertTrue(self.access.add_user(123, added_by=777))
        self.assertTrue(self.access.contains(123))
        self.assertEqual(self.access.list_users(), [123])
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute("SELECT created_at, added_by FROM allowed_users").fetchone()
        self.assertTrue(row[0].endswith("Z"))
        self.assertEqual(row[1], 777)

    def test_repeated_add_preserves_metadata(self):
        self.access.add_user(123, added_by=777)
        with closing(sqlite3.connect(self.path)) as connection:
            original = connection.execute("SELECT * FROM allowed_users").fetchall()
        self.assertFalse(self.access.add_user(123, added_by=888))
        self.access.initialize([123])
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT * FROM allowed_users").fetchall(), original)

    def test_remove_existing_and_missing_user(self):
        self.access.add_user(123)
        self.assertTrue(self.access.remove_user(123))
        self.assertFalse(self.access.contains(123))
        self.assertFalse(self.access.remove_user(123))

    def test_admin_access_independent_of_table(self):
        self.assertTrue(self.access.has_access(777, frozenset({777})))
        self.assertFalse(self.access.contains(777))
        self.assertFalse(self.access.has_access(123, frozenset({777})))
        self.access.add_user(123)
        self.assertTrue(self.access.has_access(123, frozenset({777})))

    def test_seed_import_on_each_start_and_persistence(self):
        self.access.initialize([456, 123, 123])
        self.access.add_user(999)
        reopened = AccessStore(self.path)
        reopened.initialize([456, 123])
        self.assertEqual(reopened.list_users(), [123, 456, 999])
        reopened.remove_user(123)
        reopened.remove_user(999)
        reopened.initialize([456, 123])
        self.assertEqual(reopened.list_users(), [123, 456])

    def test_concurrent_duplicate_add(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(self.access.add_user, [123] * 8))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(self.access.list_users(), [123])

    def test_invalid_ids_and_sql_input_are_rejected(self):
        for invalid in (0, -1, True, 1.5, 2**63, "1); DROP TABLE allowed_users;--"):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                self.access.add_user(invalid)
        self.assertEqual(self.access.list_users(), [])

    def test_id_parser(self):
        self.assertEqual(parse_telegram_id(" 123 "), 123)
        self.assertEqual(parse_telegram_id("12345678901"), 12345678901)
        self.assertEqual(parse_telegram_id(str(2**63 - 1)), 2**63 - 1)
        for value in ("", "0", "-1", "+1", "1 2", "1.0", "١٢٣", "9" * 100, str(2**63)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_telegram_id(value)
