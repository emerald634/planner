"""Review-only additive schema5, never imported by Store/startup.

reset_pending plus a NULL hash is a proposed design, not production approval.
No password hashing, login normalization or rate/retention defaults live here.
"""
import hashlib
import json
import sqlite3

TARGET_VERSION = 5

# Frozen from a newly created synthetic schema4, never a working DB.
BASELINE_OBJECTS = (
    ('index', 'audit_plan', 'audit', 'CREATE INDEX audit_plan ON audit(plan_id,id)'),
    ('index', 'one_pending_goal', 'goal_requests', "CREATE UNIQUE INDEX one_pending_goal ON goal_requests(task_id,field) WHERE status='pending'"),
    ('index', 'one_timer_per_employee', 'tasks', 'CREATE UNIQUE INDEX one_timer_per_employee ON tasks(employee_id) WHERE timer_started IS NOT NULL'),
    ('index', 'sqlite_autoindex_distribution_leads_1', 'distribution_leads', None),
    ('index', 'sqlite_autoindex_distribution_tasks_1', 'distribution_tasks', None),
    ('index', 'sqlite_autoindex_distribution_tasks_2', 'distribution_tasks', None),
    ('index', 'sqlite_autoindex_distributions_1', 'distributions', None),
    ('index', 'sqlite_autoindex_distributions_2', 'distributions', None),
    ('index', 'sqlite_autoindex_employees_1', 'employees', None),
    ('index', 'sqlite_autoindex_employees_2', 'employees', None),
    ('index', 'sqlite_autoindex_import_attempts_1', 'import_attempts', None),
    ('index', 'sqlite_autoindex_plans_1', 'plans', None),
    ('index', 'sqlite_autoindex_plans_2', 'plans', None),
    ('index', 'tasks_plan', 'tasks', 'CREATE INDEX tasks_plan ON tasks(plan_id)'),
    ('table', 'audit', 'audit', 'CREATE TABLE audit (\n        id INTEGER PRIMARY KEY, plan_id INTEGER REFERENCES plans(id), entity TEXT NOT NULL, entity_id INTEGER NOT NULL,\n        actor_id INTEGER NOT NULL REFERENCES employees(id), action TEXT NOT NULL,\n        before_json TEXT, after_json TEXT, created_at INTEGER NOT NULL)'),
    ('table', 'distribution_leads', 'distribution_leads', "CREATE TABLE distribution_leads(distribution_id TEXT NOT NULL REFERENCES distributions(id),lead_id INTEGER NOT NULL,employee_id INTEGER NOT NULL REFERENCES employees(id),created_date TEXT NOT NULL,initial_stage TEXT NOT NULL CHECK(initial_stage='IN_PROCESS'),PRIMARY KEY(distribution_id,lead_id))"),
    ('table', 'distribution_tasks', 'distribution_tasks', "CREATE TABLE distribution_tasks(distribution_id TEXT NOT NULL REFERENCES distributions(id),employee_id INTEGER NOT NULL REFERENCES employees(id),task_id INTEGER UNIQUE REFERENCES tasks(id),status TEXT NOT NULL CHECK(status IN ('imported','review')),PRIMARY KEY(distribution_id,employee_id))"),
    ('table', 'distributions', 'distributions', "CREATE TABLE distributions(id TEXT PRIMARY KEY,workday TEXT NOT NULL UNIQUE,sha256 TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('imported','review')),reason TEXT NOT NULL,imported_at INTEGER NOT NULL)"),
    ('table', 'employees', 'employees', "CREATE TABLE employees (\n        id INTEGER PRIMARY KEY, telegram_id INTEGER UNIQUE CHECK(telegram_id > 0),\n        bitrix_id INTEGER UNIQUE CHECK(bitrix_id > 0), name TEXT NOT NULL,\n        role TEXT NOT NULL CHECK(role IN ('manager','supervisor')), active INTEGER NOT NULL DEFAULT 1)"),
    ('table', 'goal_requests', 'goal_requests', "CREATE TABLE goal_requests (\n        id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id),\n        employee_id INTEGER NOT NULL REFERENCES employees(id), field TEXT NOT NULL CHECK(field IN ('target','planned_minutes')),\n        old_value REAL, proposed REAL NOT NULL, reason TEXT NOT NULL,\n        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','cancelled')),\n        created_at INTEGER NOT NULL, decided_at INTEGER, decided_by INTEGER REFERENCES employees(id), decision_comment TEXT NOT NULL DEFAULT '')"),
    ('table', 'import_attempts', 'import_attempts', "CREATE TABLE import_attempts(id TEXT PRIMARY KEY,status TEXT NOT NULL CHECK(status IN ('imported','review','error')),attempts INTEGER NOT NULL,last_attempt INTEGER NOT NULL,error_code TEXT NOT NULL)"),
    ('table', 'plans', 'plans', "CREATE TABLE plans (\n        id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id), day TEXT NOT NULL,\n        status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','approved','closed')),\n        initial_snapshot TEXT, created_at INTEGER NOT NULL, approved_at INTEGER, approved_by INTEGER REFERENCES employees(id),\n        closed_at INTEGER, UNIQUE(employee_id, day), UNIQUE(id, employee_id))"),
    ('table', 'reports', 'reports', 'CREATE TABLE reports (\n        plan_id INTEGER PRIMARY KEY REFERENCES plans(id), snapshot TEXT NOT NULL, closed_by INTEGER NOT NULL REFERENCES employees(id),\n        created_at INTEGER NOT NULL)'),
    ('table', 'schema_migrations', 'schema_migrations', 'CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at INTEGER NOT NULL,details TEXT NOT NULL)'),
    ('table', 'system_audit', 'system_audit', 'CREATE TABLE system_audit(id INTEGER PRIMARY KEY,plan_id INTEGER REFERENCES plans(id),entity TEXT NOT NULL,entity_id INTEGER NOT NULL,action TEXT NOT NULL,after_json TEXT NOT NULL,created_at INTEGER NOT NULL)'),
    ('table', 'tasks', 'tasks', "CREATE TABLE tasks (\n        id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL, employee_id INTEGER NOT NULL,\n        title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',\n        kind TEXT NOT NULL CHECK(kind IN ('quantitative','general','client','bitrix')),\n        planned_minutes INTEGER NOT NULL DEFAULT 0 CHECK(planned_minutes >= 0), target REAL,\n        actual_value REAL NOT NULL DEFAULT 0, actual_seconds INTEGER NOT NULL DEFAULT 0 CHECK(actual_seconds >= 0),\n        timer_started INTEGER, status TEXT NOT NULL DEFAULT 'todo' CHECK(status IN ('todo','in_progress','done','moved')),\n        result TEXT NOT NULL DEFAULT '', comment TEXT NOT NULL DEFAULT '',\n        created_by INTEGER NOT NULL REFERENCES employees(id), locked INTEGER NOT NULL DEFAULT 0,\n        revision INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL,\n        moved_to INTEGER REFERENCES tasks(id), source_task_id INTEGER REFERENCES tasks(id),\n        external_id TEXT, external_url TEXT, external_status TEXT, work_done_today INTEGER NOT NULL DEFAULT 0,\n        deadline_outcome TEXT CHECK(deadline_outcome IN ('work_done_and_moved','deadline_only')), creation_actor TEXT NOT NULL DEFAULT 'employee' CHECK(creation_actor IN ('employee','system')),\n        FOREIGN KEY(plan_id, employee_id) REFERENCES plans(id, employee_id))"),
    ('trigger', 'immutable_audit_delete', 'audit', "CREATE TRIGGER immutable_audit_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'Immutable audit'); END"),
    ('trigger', 'immutable_audit_update', 'audit', "CREATE TRIGGER immutable_audit_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'Immutable audit'); END"),
    ('trigger', 'immutable_report_delete', 'reports', "CREATE TRIGGER immutable_report_delete BEFORE DELETE ON reports BEGIN SELECT RAISE(ABORT,'Immutable report'); END"),
    ('trigger', 'immutable_report_update', 'reports', "CREATE TRIGGER immutable_report_update BEFORE UPDATE ON reports BEGIN SELECT RAISE(ABORT,'Immutable report'); END"),
    ('trigger', 'immutable_system_delete', 'system_audit', "CREATE TRIGGER immutable_system_delete BEFORE DELETE ON system_audit BEGIN SELECT RAISE(ABORT,'Immutable system audit'); END"),
    ('trigger', 'immutable_system_update', 'system_audit', "CREATE TRIGGER immutable_system_update BEFORE UPDATE ON system_audit BEGIN SELECT RAISE(ABORT,'Immutable system audit'); END"),
)

DDL = (
    """CREATE TABLE web_credentials (
        id INTEGER PRIMARY KEY CHECK(id>0), employee_id INTEGER NOT NULL UNIQUE REFERENCES employees(id) ON DELETE RESTRICT,
        login_normalized TEXT NOT NULL UNIQUE CHECK(length(login_normalized)>0),
        password_hash TEXT, active INTEGER NOT NULL CHECK(active IN (0,1)),
        state TEXT NOT NULL CHECK(state IN ('invited','ready','reset_pending')),
        credential_version INTEGER NOT NULL CHECK(typeof(credential_version)='integer' AND credential_version>=1),
        created_at INTEGER NOT NULL CHECK(typeof(created_at)='integer' AND created_at>=0), updated_at INTEGER NOT NULL CHECK(typeof(updated_at)='integer' AND updated_at>=created_at),
        CHECK((state='ready' AND password_hash IS NOT NULL AND length(password_hash)>0)
            OR (state IN ('invited','reset_pending') AND password_hash IS NULL)))""",
    """CREATE TABLE web_sessions (
        token_hash TEXT PRIMARY KEY NOT NULL CHECK(length(token_hash)=64 AND token_hash NOT GLOB '*[^0-9a-f]*'),
        credential_id INTEGER NOT NULL REFERENCES web_credentials(id) ON DELETE RESTRICT,
        credential_version INTEGER NOT NULL CHECK(typeof(credential_version)='integer' AND credential_version>=1),
        issued_at INTEGER NOT NULL CHECK(typeof(issued_at)='integer' AND issued_at>=0), last_visited_at INTEGER NOT NULL CHECK(typeof(last_visited_at)='integer'),
        absolute_expires_at INTEGER NOT NULL CHECK(typeof(absolute_expires_at)='integer'), revoked_at INTEGER,
        CHECK(issued_at<=last_visited_at AND last_visited_at<absolute_expires_at),
        CHECK(absolute_expires_at=issued_at+7776000), CHECK(revoked_at IS NULL OR (typeof(revoked_at)='integer' AND revoked_at>=issued_at)))""",
    "CREATE INDEX web_sessions_credential ON web_sessions(credential_id)",
    "CREATE INDEX web_sessions_expiry ON web_sessions(absolute_expires_at)",
    "CREATE INDEX web_sessions_visit ON web_sessions(last_visited_at)",
    """CREATE TABLE web_password_actions (
        id INTEGER PRIMARY KEY CHECK(id>0), token_hash TEXT NOT NULL UNIQUE
          CHECK(length(token_hash)=64 AND token_hash NOT GLOB '*[^0-9a-f]*'),
        credential_id INTEGER NOT NULL REFERENCES web_credentials(id) ON DELETE RESTRICT,
        credential_version INTEGER NOT NULL CHECK(typeof(credential_version)='integer' AND credential_version>=1),
        purpose TEXT NOT NULL CHECK(purpose IN ('invitation','reset')),
        issued_by INTEGER NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
        issued_at INTEGER NOT NULL CHECK(typeof(issued_at)='integer' AND issued_at>=0), expires_at INTEGER NOT NULL CHECK(typeof(expires_at)='integer'),
        used_at INTEGER, revoked_at INTEGER,
        CHECK(expires_at>issued_at), CHECK(purpose!='reset' OR expires_at=issued_at+1800),
        CHECK(used_at IS NULL OR (typeof(used_at)='integer' AND used_at>=issued_at AND used_at<expires_at)),
        CHECK(revoked_at IS NULL OR (typeof(revoked_at)='integer' AND revoked_at>=issued_at)))""",
    "CREATE UNIQUE INDEX web_action_pending ON web_password_actions(credential_id,purpose) WHERE used_at IS NULL AND revoked_at IS NULL",
    "CREATE INDEX web_action_expiry ON web_password_actions(expires_at)",
    """CREATE TABLE web_login_attempts (
        id INTEGER PRIMARY KEY CHECK(id>0), login_bucket TEXT NOT NULL CHECK(length(login_bucket)>0),
        source_bucket TEXT NOT NULL CHECK(length(source_bucket)>0), occurred_at INTEGER NOT NULL CHECK(typeof(occurred_at)='integer' AND occurred_at>=0),
        outcome TEXT NOT NULL CHECK(outcome IN ('denied','limited','accepted')))""",
    "CREATE INDEX web_attempt_login ON web_login_attempts(login_bucket,occurred_at)",
    "CREATE INDEX web_attempt_source ON web_login_attempts(source_bucket,occurred_at)",
    """CREATE TABLE web_auth_audit (
        id INTEGER PRIMARY KEY CHECK(id>0), event TEXT NOT NULL CHECK(event IN
          ('credential_created','credential_disabled','reset_started','reset_completed','session_revoked','login_denied','login_accepted')),
        actor_kind TEXT NOT NULL CHECK(actor_kind IN ('employee','system')),
        actor_employee_id INTEGER REFERENCES employees(id) ON DELETE RESTRICT,
        target_employee_id INTEGER REFERENCES employees(id) ON DELETE RESTRICT,
        occurred_at INTEGER NOT NULL CHECK(typeof(occurred_at)='integer' AND occurred_at>=0), correlation_id TEXT NOT NULL,
        CHECK((actor_kind='employee' AND actor_employee_id IS NOT NULL)
          OR (actor_kind='system' AND actor_employee_id IS NULL)))""",
    "CREATE INDEX web_audit_actor ON web_auth_audit(actor_employee_id,occurred_at)",
    "CREATE INDEX web_audit_target ON web_auth_audit(target_employee_id,occurred_at)",
)


def objects(db):
    return tuple(tuple(row) for row in db.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"))


def manifest():
    """Build expected auth objects in memory, without opening application files."""
    db = sqlite3.connect(":memory:")
    try:
        for statement in DDL:
            db.execute(statement)
        return objects(db)
    finally:
        db.close()


AUTH_OBJECTS = manifest()
MANIFEST_CHECKSUM = hashlib.sha256(json.dumps(AUTH_OBJECTS, ensure_ascii=True,
    separators=(",", ":")).encode("ascii")).hexdigest()
REGISTRY_DETAILS = json.dumps({"component": "web_auth_foundation", "design": "review-only",
    "manifest_sha256": MANIFEST_CHECKSUM}, sort_keys=True, separators=(",", ":"))
