import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from planner.web_auth.migration import migrate_synthetic
from planner.web_auth.schema import AUTH_OBJECTS
from tests.web_auth_fixtures import connect, create_schema4, digest, seed_auth


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix="web-auth-schema-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "synthetic.db"
        create_schema4(self.path)
        self.db = connect(self.path)
        self.addCleanup(self.db.close)
        migrate_synthetic(self.db, applied_at=1)
        seed_auth(self.db)

    def invalid(self, sql, params=()):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db:
                self.db.execute(sql, params)

    def test_credential_unique_fk_state_hash_and_version(self):
        sql = "INSERT INTO web_credentials VALUES(?,?,?,?,?,?,?,?,?)"
        for row in ((2, 1, "another", "opaque", 1, "ready", 1, 1, 1),
                    (2, 2, "synthetic-manager", "opaque", 1, "ready", 1, 1, 1),
                    (2, 999, "another", "opaque", 1, "ready", 1, 1, 1),
                    (2, 2, "another", None, 1, "ready", 1, 1, 1),
                    (2, 2, "another", "opaque", 1, "reset_pending", 1, 1, 1),
                    (2, 2, "another", "opaque", 2, "ready", 1, 1, 1),
                    (2, 2, "another", "opaque", 1, "ready", 0, 1, 1),
                    (2, 2, "another", "opaque", 1, "ready", 1.5, 1, 1),
                    (2, 2, "another", "opaque", 1, "ready", 1, "invalid", "invalid"),
                    (2, 2, "", "opaque", 1, "ready", 1, 1, 1)):
            with self.subTest(row=row):
                self.invalid(sql, row)
        self.invalid("DELETE FROM employees WHERE id=1")

    def test_session_unique_fk_hash_and_time_constraints(self):
        sql = "INSERT INTO web_sessions VALUES(?,?,?,?,?,?,?)"
        for row in ((digest("old-session"), 1, 1, 10000, 10000, 7786000, None),
                    (digest("new-session"), 999, 1, 10000, 10000, 7786000, None),
                    (None, 1, 1, 10000, 10000, 7786000, None),
                    ("raw-token", 1, 1, 10000, 10000, 7786000, None),
                    (digest("new-session"), 1, 1, 10000, 9999, 7786000, None),
                    (digest("new-session"), 1, 1, 10000, 10000, 7786001, None),
                    (digest("new-session"), 1, 1, 10000, 10000, 7786000, 9999)):
            with self.subTest(row=row):
                self.invalid(sql, row)

    def test_action_uniqueness_fk_purpose_and_one_time_constraints(self):
        sql = "INSERT INTO web_password_actions(token_hash,credential_id,credential_version,purpose,issued_by,issued_at,expires_at,used_at) VALUES(?,?,?,?,?,?,?,?)"
        valid = (digest("code"), 1, 1, "reset", 3, 100, 1900, None)
        with self.db:
            self.db.execute(sql, valid)
        for row in (valid, (digest("code2"), *valid[1:]),
                    (digest("code2"), 999, 1, "reset", 3, 100, 1900, None),
                    (digest("code2"), 1, 1, "other", 3, 100, 1900, None),
                    (digest("code2"), 1, 1, "reset", 999, 100, 1900, None),
                    (digest("code2"), 1, 1, "reset", 3, 100, 1901, None),
                    (digest("code2"), 1, 1, "invitation", 3, 100, 500, 500)):
            self.invalid(sql, row)
        with self.db:
            self.db.execute("UPDATE web_password_actions SET revoked_at=101 WHERE id=1")
            self.db.execute(sql, (digest("code2"), *valid[1:]))
        self.assertEqual(self.db.execute("SELECT count(*) FROM web_password_actions").fetchone()[0], 2)

    def test_closed_audit_and_attempt_enums_and_actor_foreign_keys(self):
        self.invalid("INSERT INTO web_login_attempts VALUES(1,'login','source',1,'unknown')")
        self.invalid("INSERT INTO web_auth_audit VALUES(1,'reset_started','employee',NULL,1,1,'correlation')")
        self.invalid("INSERT INTO web_auth_audit VALUES(1,'reset_started','system',3,1,1,'correlation')")
        self.invalid("INSERT INTO web_auth_audit VALUES(1,'reset_started','employee',999,1,1,'correlation')")
        with self.db:
            self.db.execute("INSERT INTO web_auth_audit VALUES(1,'session_revoked','system',NULL,1,1,'correlation')")

    def test_indexes_fk_integrity_and_no_cascade_or_role_copy(self):
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(web_credentials)")}
        self.assertFalse({"role", "telegram_id"} & columns)
        for kind, name, table, sql in AUTH_OBJECTS:
            if kind == "table":
                for fk in self.db.execute(f'PRAGMA foreign_key_list("{table}")'):
                    self.assertEqual(fk[6], "RESTRICT")
            if kind == "index" and sql:
                self.assertIsNotNone(self.db.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone())
        index = self.db.execute("SELECT sql FROM sqlite_master WHERE name='web_action_pending'").fetchone()[0]
        self.assertIn("UNIQUE", index)
        self.assertIn("WHERE used_at IS NULL AND revoked_at IS NULL", index)
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.db.execute("PRAGMA integrity_check").fetchone(), ("ok",))
