"""Crash reconciliation for broker leases, without automatic retries."""
import sqlite3

from .worker_leases import expire_jobs


def reconcile_worker_leases(db: sqlite3.Connection) -> dict[str, int]:
    """Revoke orphaned leases and fail abandoned download tasks.

    Does not touch uploading tasks (Telegram delivery may be ambiguous).
    No job is automatically restarted.
    """
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    if db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='worker_job_leases'"
    ).fetchone() is None:
        return {"expired": 0, "revoked": 0, "failed": 0}
    expired = expire_jobs(db)
    db.execute(
        """UPDATE worker_job_leases SET state='cancelled'
        WHERE state IN ('offered','running') AND EXISTS (
            SELECT 1 FROM tasks WHERE tasks.id=worker_job_leases.task_id
            AND tasks.status NOT IN ('downloading','processing')
        )"""
    )
    revoked = db.execute("SELECT changes()").fetchone()[0]
    db.execute(
        """UPDATE tasks SET status='failed'
        WHERE status IN ('downloading','processing') AND id IN (
            SELECT task_id FROM worker_job_leases
            WHERE state IN ('expired','cancelled')
        )"""
    )
    failed = db.execute("SELECT changes()").fetchone()[0]
    return {"expired": expired, "revoked": revoked, "failed": failed}
