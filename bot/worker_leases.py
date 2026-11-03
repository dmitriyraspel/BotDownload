"""Durable, fail-closed broker leases for future isolated media jobs.

Only the trusted bot-side broker writes this table. A separate worker never
receives SQL write access or executable commands. No media execution here.
"""
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

_STATES = ("offered", "running", "finished", "cancelled", "expired")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS worker_job_leases (
 task_id INTEGER PRIMARY KEY REFERENCES tasks(id),
 token_hash TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('offered','running','finished','cancelled','expired')),
 expires_at TEXT NOT NULL
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_id(task_id: int) -> None:
    if type(task_id) is not int or not 0 < task_id <= 9223372036854775807:
        raise ValueError("Некорректный ID задачи")


def _validate_ttl(ttl_seconds: int) -> None:
    if type(ttl_seconds) is not int or not 0 < ttl_seconds <= 3600:
        raise ValueError("Некорректный срок аренды")


def _expiry(ttl_seconds: int) -> str:
    return (_now() + timedelta(seconds=ttl_seconds)).isoformat()


def _begin(db: sqlite3.Connection) -> None:
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")


def offer_job(db: sqlite3.Connection, task_id: int, *, ttl_seconds: int = 60) -> str | None:
    """Offer one already-claimed task exactly once; return opaque capability.

    A failed offer does not modify the existing lease.
    """
    _validate_id(task_id)
    _validate_ttl(ttl_seconds)
    _begin(db)
    db.executescript(_SCHEMA) if False else None
    db.execute(_SCHEMA)
    row = db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
    if row is None or row[0] != "downloading":
        return None
    if db.execute("SELECT 1 FROM worker_job_leases WHERE task_id=?", (task_id,)).fetchone():
        return None
    token = secrets.token_hex(32)
    import hashlib
    db.execute(
        "INSERT INTO worker_job_leases(task_id,token_hash,state,expires_at) VALUES (?,?,?,?)",
        (task_id, hashlib.sha256(token.encode()).hexdigest(), "offered", _expiry(ttl_seconds)),
    )
    return token


def transition_job(db: sqlite3.Connection, task_id: int, token: str,
                   from_state: str, to_state: str) -> bool:
    """CAS transition; never resurrect expired/cancelled work."""
    _validate_id(task_id)
    if (type(token) is not str or len(token) != 64
            or any(c not in "0123456789abcdef" for c in token)):
        return False
    if (from_state, to_state) not in {
        ("offered", "running"), ("running", "finished"),
        ("offered", "cancelled"), ("running", "cancelled"),
    }:
        return False
    import hashlib
    _begin(db)
    db.execute(_SCHEMA)
    cursor = db.execute(
        """UPDATE worker_job_leases SET state=?
        WHERE task_id=? AND token_hash=? AND state=?
        AND expires_at>? AND EXISTS(
          SELECT 1 FROM tasks WHERE id=?
          AND status='downloading'
        )""",
        (to_state, task_id, hashlib.sha256(token.encode()).hexdigest(),
         from_state, _now().isoformat(), task_id),
    )
    return cursor.rowcount == 1


def expire_jobs(db: sqlite3.Connection) -> int:
    """Expire timed-out leases; does not automatically retry media work."""
    _begin(db)
    db.execute(_SCHEMA)
    cursor = db.execute(
        """UPDATE worker_job_leases SET state='expired'
        WHERE state IN ('offered','running') AND expires_at<=?""",
        (_now().isoformat(),),
    )
    return cursor.rowcount


def cancel_job(db: sqlite3.Connection, task_id: int) -> bool:
    """Revoke outstanding capability after a task cancellation."""
    _validate_id(task_id)
    _begin(db)
    db.execute(_SCHEMA)
    cursor = db.execute(
        """UPDATE worker_job_leases SET state='cancelled'
        WHERE task_id=? AND state IN ('offered','running')""", (task_id,),
    )
    return cursor.rowcount == 1
