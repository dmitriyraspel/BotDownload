"""Fail-closed queue-to-IPC orchestration for real-media jobs.

Stage 2 reserves and starts durable leases but cannot execute downloads until
network egress isolation is independently verified. No file is staged and no
Telegram upload is enabled by this module.
"""
import asyncio
import logging
from pathlib import Path

from .storage import database, claim_next_task, change_status, task_is_cancelled
from .worker_dispatch import reserve_worker_job, cancel_worker_reservation
from .worker_ipc import WorkerProtocolError
from .worker_leases import offer_job, transition_job, cancel_job


async def process_one_media_task(
    *, db_path: Path, socket_path: Path, max_wait_minutes: int = 30,
    lease_seconds: int = 60,
) -> int | None:
    """Claim exactly one task and exercise the authenticated IPC reservation.

    The worker currently has no network execution operation. A task is marked
    failed rather than generating an offline fixture or pretending success.
    """
    with database(db_path) as db:
        task_id = claim_next_task(db, max_wait_minutes=max_wait_minutes)
        token = offer_job(db, task_id, ttl_seconds=lease_seconds) if task_id is not None else None
    if task_id is None:
        return None
    if token is None:
        with database(db_path) as db:
            change_status(db, task_id, "downloading", "failed")
        return task_id
    try:
        accepted = await reserve_worker_job(socket_path, task_id, token)
        if not accepted:
            raise WorkerProtocolError("Worker отклонил резервирование")
        with database(db_path) as db:
            if not transition_job(db, task_id, token, "offered", "running"):
                raise WorkerProtocolError("Lease отозван до запуска")
        # Fail closed: execution is intentionally unavailable until kernel-level
        # egress isolation, secondary URL and redirect validation are present.
        raise WorkerProtocolError("Медиа-исполнение не разрешено без сетевой изоляции")
    except asyncio.CancelledError:
        with database(db_path) as db:
            cancel_job(db, task_id)
            change_status(db, task_id, "downloading", "failed")
        raise
    except Exception:
        logging.exception("Медиа-задача %d остановлена до исполнения", task_id)
        with database(db_path) as db:
            cancel_job(db, task_id)
            change_status(db, task_id, "downloading", "failed")
    finally:
        try:
            await asyncio.wait_for(cancel_worker_reservation(socket_path, task_id, token), timeout=3.5)
        except (WorkerProtocolError, asyncio.TimeoutError, OSError):
            pass
    return task_id


async def run_media_dispatcher(
    *, stop: asyncio.Event, db_path: Path, socket_path: Path,
    max_wait_minutes: int = 30, idle_seconds: float = 0.2,
) -> None:
    """Explicit opt-in test dispatcher; never wire to production polling."""
    if not isinstance(stop, asyncio.Event) or idle_seconds <= 0:
        raise ValueError("Некорректный dispatcher")
    while not stop.is_set():
        task_id = await process_one_media_task(
            db_path=db_path, socket_path=socket_path,
            max_wait_minutes=max_wait_minutes,
        )
        if task_id is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=idle_seconds)
            except asyncio.TimeoutError:
                pass
