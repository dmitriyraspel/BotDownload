"""Fail-closed broker orchestration for one non-executing IPC reservation.

This module does not run yt-dlp, enable network access or publish files.
"""
import asyncio
from pathlib import Path

from .storage import database
from .worker_dispatch import cancel_worker_reservation, reserve_worker_job
from .worker_ipc import WorkerProtocolError
from .worker_leases import cancel_job, offer_job, transition_job


async def reserve_claimed_task(
    *, db_path: Path, socket_path: Path, task_id: int,
    ttl_seconds: int = 60, timeout: float = 3.0,
) -> bool:
    """Offer a claimed task, reserve in worker, then atomically mark running.

    On any ambiguous IPC failure, revoke the durable lease first and
    best-effort notify the worker. Never retry an uncertain reservation.
    """
    with database(db_path) as db:
        token = offer_job(db, task_id, ttl_seconds=ttl_seconds)
    if token is None:
        return False
    accepted = False
    try:
        accepted = await reserve_worker_job(socket_path, task_id, token, timeout=timeout)
        if not accepted:
            return False
        with database(db_path) as db:
            return transition_job(db, task_id, token, "offered", "running")
    finally:
        # A successful running lease remains reserved. Every other
        # outcome is revoked even if the IPC response was lost.
        with database(db_path) as db:
            row = db.execute(
                "SELECT state FROM worker_job_leases WHERE task_id=?", (task_id,)
            ).fetchone()
            running = row is not None and row[0] == "running"
            if not running:
                cancel_job(db, task_id)
        if not running:
            try:
                await asyncio.shield(
                    cancel_worker_reservation(socket_path, task_id, token, timeout=timeout)
                )
            except (WorkerProtocolError, OSError, asyncio.CancelledError):
                pass


async def revoke_claimed_task(
    *, db_path: Path, socket_path: Path, task_id: int,
    timeout: float = 3.0,
) -> bool:
    """Revoke a broker lease; never reveal token hashes as capabilities.

    This operation cannot remotely cancel an already-running process;
    the IPC protocol currently supports only reservation cancellation.
    """
    with database(db_path) as db:
        return cancel_job(db, task_id)
