"""Synthetic-only DBs and a transaction reference model, NOT password authentication.

Opaque marker hashes are intentionally unusable as password verifiers. Nothing here
is imported by the application. These helpers exercise a proposed physical design.
"""
import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from planner.store import Store
from planner.web_auth.models import (Credential, CredentialState, Employee, Role,
                                     SESSION_LIFETIME)
from planner.web_auth.policy import can_manage_account, login_allowed
from planner.web_auth.schema import BASELINE_OBJECTS, objects

NOW = 10000
OLD_HASH = "synthetic-opaque-not-a-password-hash-v1"
NEW_HASH = "synthetic-opaque-not-a-password-hash-v2"


def digest(marker):
    return hashlib.sha256(marker.encode("ascii")).hexdigest()


def connect(path, timeout=1):
    db = sqlite3.connect(path, timeout=timeout)
    db.execute("PRAGMA foreign_keys=ON")
    return db


def create_schema4(path: Path):
    Store(path).initialize()
    db = connect(path)
    try:
        with db:
            for identity in (1, 2, 3):
                db.execute("UPDATE employees SET telegram_id=?,bitrix_id=NULL,name=? WHERE id=?",
                           (100 + identity, f"Synthetic employee {identity}", identity))
            db.execute("INSERT INTO employees(id,name,role,active) VALUES(4,'Synthetic inactive','manager',0)")
            for identity, status in ((1, "draft"), (2, "approved"), (3, "closed")):
                owner = 1 if identity == 1 else 2
                db.execute("INSERT INTO plans(id,employee_id,day,status,initial_snapshot,created_at,approved_at,approved_by,closed_at) VALUES(?,?,?,?,?,1,?,?,?)",
                           (identity, owner, f"2099-01-0{identity}", status, '{"synthetic":true}',
                            None if identity == 1 else 2, None if identity == 1 else 3,
                            3 if identity == 3 else None))
                db.execute("INSERT INTO tasks(id,plan_id,employee_id,title,kind,planned_minutes,target,actual_value,actual_seconds,timer_started,status,result,comment,created_by,created_at) VALUES(?,?,?,'Synthetic task','quantitative',60,9,4,300,?,?,'Synthetic result','Synthetic comment',3,1)",
                           (identity, identity, owner, NOW if identity == 1 else None,
                            "in_progress" if identity == 1 else "done"))
            db.execute("INSERT INTO goal_requests(task_id,employee_id,field,old_value,proposed,reason,created_at) VALUES(1,1,'target',9,10,'Synthetic request',1)")
            db.execute("INSERT INTO reports VALUES(3,'{\"synthetic\":true}',3,3)")
            db.execute("INSERT INTO audit(plan_id,entity,entity_id,actor_id,action,after_json,created_at) VALUES(1,'task',1,3,'synthetic','{}',1)")
            db.execute("INSERT INTO system_audit(plan_id,entity,entity_id,action,after_json,created_at) VALUES(1,'task',1,'synthetic','{}',1)")
            db.execute("INSERT INTO distributions VALUES('synthetic','2099-01-01',?,'{}','imported','',1)", (digest("distribution"),))
            db.execute("INSERT INTO distribution_tasks VALUES('synthetic',1,1,'imported')")
            db.execute("INSERT INTO distribution_leads VALUES('synthetic',7001,1,'2098-12-31','IN_PROCESS')")
            db.execute("INSERT INTO import_attempts VALUES('synthetic','imported',1,1,'')")
    finally:
        db.close()


def business_snapshot(db):
    """All old rows, SQL, columns, FK/index metadata; no row-count shortcuts."""
    names = {row[1] for row in BASELINE_OBJECTS}
    tables = [row[1] for row in BASELINE_OBJECTS if row[0] == "table"]
    data = {}
    for table in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        where = " WHERE version<5" if table == "schema_migrations" else ""
        data[table] = {
            "rows": sorted((tuple(row) for row in db.execute(f"SELECT * FROM {quoted}{where}")), key=repr),
            "columns": list(db.execute(f"PRAGMA table_info({quoted})")),
            "foreign_keys": list(db.execute(f"PRAGMA foreign_key_list({quoted})")),
            "indexes": list(db.execute(f"PRAGMA index_list({quoted})")),
        }
    return tuple(row for row in objects(db) if row[1] in names), data


def seed_auth(db):
    with db:
        db.execute("INSERT INTO web_credentials VALUES(1,1,'synthetic-manager',?,1,'ready',1,1,1)", (OLD_HASH,))
        db.execute("INSERT INTO web_sessions VALUES(?,1,1,?,?,?,NULL)",
                   (digest("old-session"), NOW, NOW, NOW + SESSION_LIFETIME))


@contextmanager
def transaction(path, fault=None):
    db = connect(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        yield db
        if fault:
            fault()
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def load_credential(db):
    row = db.execute("SELECT id,employee_id,active,state,credential_version,password_hash FROM web_credentials WHERE id=1").fetchone()
    return Credential(row[0], row[1], bool(row[2]), CredentialState(row[3]), row[4], row[5])


def employee(db, identity):
    row = db.execute("SELECT id,role,active FROM employees WHERE id=?", (identity,)).fetchone()
    return Employee(row[0], Role(row[1]), bool(row[2]))


def reset_model(path, code_marker, *, now=NOW+1, fault=None, supervisor_id=3):
    with transaction(path, fault) as db:
        if not can_manage_account(employee(db, supervisor_id), employee(db, 1), password_reconfirmed=True):
            raise PermissionError("Synthetic reset denied")
        db.execute("UPDATE web_credentials SET state='reset_pending',password_hash=NULL,credential_version=credential_version+1,updated_at=? WHERE id=1", (now,))
        db.execute("UPDATE web_sessions SET revoked_at=? WHERE credential_id=1 AND revoked_at IS NULL", (now,))
        db.execute("UPDATE web_password_actions SET revoked_at=? WHERE credential_id=1 AND used_at IS NULL AND revoked_at IS NULL", (now,))
        version = load_credential(db).version
        db.execute("INSERT INTO web_password_actions(token_hash,credential_id,credential_version,purpose,issued_by,issued_at,expires_at) VALUES(?,1,?,'reset',3,?,?)",
                   (digest(code_marker), version, now, now+1800))
        db.execute("INSERT INTO web_auth_audit(event,actor_kind,actor_employee_id,target_employee_id,occurred_at,correlation_id) VALUES('reset_started','employee',3,1,?,'synthetic-correlation')", (now,))


def issue_session_model(path, proof_version, marker, *, now=NOW+2):
    """proof_version models a verifier result captured BEFORE the write lock.

    It is not a password check and is never accepted by a production endpoint.
    """
    with transaction(path) as db:
        credential = load_credential(db)
        if not login_allowed(employee(db, 1), credential) or credential.version != proof_version:
            return False
        db.execute("INSERT INTO web_sessions VALUES(?,1,?,?,?,?,NULL)",
                   (digest(marker), proof_version, now, now, now+SESSION_LIFETIME))
        return True


def redeem_model(path, marker, *, now=NOW+3, fault=None):
    with transaction(path, fault) as db:
        credential = load_credential(db)
        row = db.execute("SELECT id,credential_version,issued_at,expires_at,used_at,revoked_at FROM web_password_actions WHERE token_hash=? AND credential_id=1 AND purpose='reset'", (digest(marker),)).fetchone()
        if (row is None or row[1] != credential.version or row[4] is not None
                or row[5] is not None or not row[2] <= now < row[3]
                or credential.state != CredentialState.RESET_PENDING
                or not credential.active or not employee(db, 1).active):
            return False
        db.execute("UPDATE web_password_actions SET used_at=? WHERE id=?", (now, row[0]))
        db.execute("UPDATE web_credentials SET state='ready',password_hash=?,credential_version=credential_version+1,updated_at=? WHERE id=1", (NEW_HASH, now))
        db.execute("INSERT INTO web_auth_audit(event,actor_kind,actor_employee_id,target_employee_id,occurred_at,correlation_id) VALUES('reset_completed','employee',1,1,?,'synthetic-correlation')", (now,))
        return True
