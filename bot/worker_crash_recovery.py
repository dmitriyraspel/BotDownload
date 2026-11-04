"""Fail-closed reconciliation after the supervised worker has exited."""
from pathlib import Path

from .storage import database


def reconcile_confirmed_worker_exit(db_path: Path) -> int:
    """Only call after worker.wait() confirms process termination."""
    with database(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='worker_job_leases'"
        ).fetchone()
        if table is None:
            return 0
        db.execute(
            """UPDATE worker_job_leases SET state='cancelled'
            WHERE state IN ('offered','running')"""
        )
        changed = db.execute(
            """UPDATE tasks SET status='failed'
            WHERE status IN ('downloading','processing')
            AND id IN (SELECT task_id FROM worker_job_leases
                       WHERE state IN ('cancelled','expired'))"""
        ).rowcount
        return changed
