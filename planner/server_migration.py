"""Explicit additive core4 extension. No startup migration or employee seeds."""

import json
import time


def migrate_server(store):

    # All DDL in ONE transaction, including earlier RC1 extension operations.
    with store.connection(True) as db:
        if db.execute("PRAGMA user_version").fetchone()[0] != 4:
            raise ValueError("Expected reviewed core schema4")
        db.execute(
            "CREATE TABLE IF NOT EXISTS daily_extension(version INTEGER PRIMARY KEY CHECK(version=1))"
        )
        db.execute("INSERT OR IGNORE INTO daily_extension VALUES(1)")
        db.execute(
            "CREATE TABLE IF NOT EXISTS daily_records(plan_id INTEGER PRIMARY KEY REFERENCES plans(id),revision INTEGER NOT NULL,payload TEXT NOT NULL,updated_at INTEGER NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS web_distribution_previews(id TEXT PRIMARY KEY,actor_id INTEGER NOT NULL REFERENCES employees(id),workday TEXT NOT NULL,payload TEXT NOT NULL,created_at INTEGER NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS workspace_extensions(name TEXT PRIMARY KEY,version INTEGER NOT NULL)"
        )
        old = db.execute(
            "SELECT version FROM workspace_extensions WHERE name='crm_observations'"
        ).fetchone()
        if old and old[0] != 1:
            raise ValueError("Unknown extension version")
        db.execute(
            "CREATE TABLE IF NOT EXISTS crm_observations(plan_id INTEGER NOT NULL REFERENCES plans(id),source TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(plan_id,source))"
        )
        db.execute(
            "INSERT OR IGNORE INTO workspace_extensions VALUES('crm_observations',1)"
        )


def save_observation(store, actor, plan_id, source, observation, verified_contracts):
    value = dict(observation)
    value["auto_verified"] = (
        source in verified_contracts and value["status"] == "verified"
    )
    with store.connection(True) as db:
        store.plan(db, actor, plan_id, True)
        # Keep prior last-good projection on failure, labelled stale, never as new fact.
        old = db.execute(
            "SELECT payload FROM crm_observations WHERE plan_id=? AND source=?",
            (plan_id, source),
        ).fetchone()
        if value["status"] != "verified" and old:
            previous = json.loads(old[0])
            value.update(
                last_good=previous.get("last_good") or previous, auto_verified=False
            )
        db.execute(
            "INSERT INTO crm_observations VALUES(?,?,?) ON CONFLICT(plan_id,source) DO UPDATE SET payload=excluded.payload",
            (
                plan_id,
                source,
                json.dumps(value, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        store.audit(
            db,
            actor,
            "source",
            plan_id,
            "source_refreshed",
            None,
            {
                "source": source,
                "status": value["status"],
                "updated_at": value["updated_at"],
            },
            plan_id,
        )
    return value


def cached_observation(store, actor, plan_id, kind):
    with store.connection() as db:
        store.plan(db, actor, plan_id)
        row = db.execute(
            "SELECT payload FROM crm_observations WHERE plan_id=? AND source=?",
            (plan_id, kind),
        ).fetchone()
    return json.loads(row[0]) if row else None


def seed_verified_draft(db, plan, data):
    """Only an UNSAVED draft. Never replace any saved manual fact or approved goal."""
    if plan["status"] != "draft" or data["revision"] != 0:
        return
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='crm_observations'"
    ).fetchone():
        return
    rows = {r["key"]: r for r in data["indicators"]}
    allowed = {"calls.actual", "new_leads.planned", "pain.planned"}
    for row in db.execute(
        "SELECT payload FROM crm_observations WHERE plan_id=?", (plan["id"],)
    ):
        observation = json.loads(row[0])
        if (
            not observation.get("auto_verified")
            or time.time() - observation["updated_at"] > 900
        ):
            continue
        for key, value in observation.get("projection", {}).items():
            if key not in allowed or type(value) is not int or value < 0:
                continue
            indicator, field = key.split(".")
            rows[indicator][field] = value
            rows[indicator]["source"] = (
                "Bitrix24: проверенный контракт, первичное заполнение черновика"
            )
            rows[indicator]["remaining"] = max(
                0, rows[indicator]["planned"] - rows[indicator]["actual"]
            )


def freeze_daily(db, store, actor, plan_id):
    # Called in the existing confirmation/close transaction, BEFORE status changes.
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='daily_records'"
    ).fetchone():
        return
    if db.execute("SELECT 1 FROM daily_records WHERE plan_id=?", (plan_id,)).fetchone():
        return
    from .daily import DailyStore, Detail

    daily = DailyStore(store.path).daily_detail(db, actor, plan_id)
    rows = []
    for row in daily["indicators"]:
        value = {
            key: row[key] for key in ("key", "planned", "actual", "morning", "details")
        }
        value["details"] = [
            {k: v for k, v in item.items() if k in Detail.model_fields}
            for item in value["details"]
        ]
        rows.append(value)
    payload = {
        "indicators": rows,
        "contracts": daily["contracts"],
        "seed_sources": {
            r["key"]: r["source"].replace(
                "первичное заполнение черновика", "снимок при подтверждении"
            )
            for r in daily["indicators"]
            if r["source"].startswith("Bitrix24:")
        },
    }
    db.execute(
        "INSERT INTO daily_records VALUES(?,1,?,?)",
        (plan_id, json.dumps(payload, ensure_ascii=False), int(time.time())),
    )
    db.execute(
        "INSERT INTO system_audit(plan_id,entity,entity_id,action,after_json,created_at) VALUES(?,'daily',?,'daily_frozen_for_confirmation',?,?)",
        (
            plan_id,
            plan_id,
            json.dumps({"revision": 1, "initiated_by_employee_id": actor["id"]}),
            int(time.time()),
        ),
    )
