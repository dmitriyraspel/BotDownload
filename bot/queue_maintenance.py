"""Safe production queue maintenance while media downloads remain disabled.

Never claim queued media jobs or stage offline fixtures for Telegram delivery.
"""
import asyncio
import logging
from pathlib import Path

from .storage import database
from .worker_recovery import reconcile_worker_leases


def maintain_queue(db_path: Path, *, max_wait_minutes: int = 30) -> tuple[int, int]:
    """Expire stale queued jobs and reconcile revoked/expired leases atomically."""
    if type(max_wait_minutes) is not int or max_wait_minutes <= 0:
        raise ValueError("max_wait_minutes должен быть положительным")
    with database(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        expired = db.execute(
            """UPDATE tasks SET status='failed'
            WHERE status='queued' AND created_at <
            strftime('%Y-%m-%dT%H:%M:%fZ','now', ?)""",
            (f"-{max_wait_minutes} minutes",),
        ).rowcount
        reconciled = reconcile_worker_leases(db)
    return expired, reconciled["failed"]


async def run_queue_maintenance(
    *, stop: asyncio.Event, db_path: Path,
    max_wait_minutes: int = 30, idle_seconds: float = 1.0,
) -> None:
    """One non-executing dispatcher loop; no synthetic uploads."""
    if idle_seconds <= 0:
        raise ValueError("idle_seconds должен быть положительным")
    while not stop.is_set():
        try:
            expired, failed = maintain_queue(
                db_path, max_wait_minutes=max_wait_minutes,
            )
            if expired or failed:
                logging.info("Очередь: просрочено %d, отозвано %d", expired, failed)
        except Exception:
            logging.exception("Ошибка обслуживания очереди")
        try:
            await asyncio.wait_for(stop.wait(), timeout=idle_seconds)
        except asyncio.TimeoutError:
            pass
