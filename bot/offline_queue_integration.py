"""Opt-in end-to-end OFFLINE queue -> IPC -> worker -> staged file.

Never invoked by the Telegram polling entrypoint. No network/media support.
"""
import asyncio
import logging
from pathlib import Path

from .file_lifecycle import prepare_claimed_file_task
from .storage import claim_next_task, database, change_status, task_is_cancelled
from .worker_dispatch import cancel_worker_reservation, reserve_worker_job
from .worker_ipc import WorkerProtocolError
from .worker_leases import cancel_job, offer_job, transition_job
from .worker_offline_client import execute_offline_ipc


async def process_one_offline_task(
    *, db_path: Path, socket_path: Path, configured_download_dir: str,
    max_wait_minutes: int = 30, project_root: Path = Path("."),
    reserve_bytes: int = 0,
) -> int | None:
    """Process one task with fixed offline fixture and stage for upload.

    The staged file is a test artifact, NOT a playable media file.
    """
    with database(db_path) as db:
        task_id = claim_next_task(db, max_wait_minutes=max_wait_minutes)
        token = offer_job(db, task_id, ttl_seconds=60) if task_id is not None else None
    if task_id is None:
        return None
    if token is None:
        with database(db_path) as db:
            change_status(db, task_id, "downloading", "failed")
        return task_id
    running = False
    finished = False
    try:
        if not await reserve_worker_job(socket_path, task_id, token):
            raise WorkerProtocolError("Worker отклонил задачу")
        with database(db_path) as db:
            running = transition_job(db, task_id, token, "offered", "running")
        if not running:
            raise WorkerProtocolError("Задача отменена до запуска")
        async def watch_cancellation():
            while True:
                with database(db_path) as db:
                    if task_is_cancelled(db, task_id):
                        return
                await asyncio.sleep(0.05)

        execution = asyncio.create_task(execute_offline_ipc(socket_path, task_id, token))
        cancellation = asyncio.create_task(watch_cancellation())
        try:
            done, _ = await asyncio.wait(
                (execution, cancellation), return_when=asyncio.FIRST_COMPLETED,
            )
            if cancellation in done:
                execution.cancel()
                try:
                    await execution
                except asyncio.CancelledError:
                    pass
                with database(db_path) as db:
                    cancel_job(db, task_id)
                await cancel_worker_reservation(socket_path, task_id, token)
                return task_id
            payload = await execution
        finally:
            cancellation.cancel()
            try:
                await cancellation
            except asyncio.CancelledError:
                pass
        with database(db_path) as db:
            finished = transition_job(db, task_id, token, "running", "finished")
        if not finished:
            raise WorkerProtocolError("Задача отозвана до завершения")

        async def processor(workspace: Path, _task_id: int) -> str:
            target = workspace / "offline-result.bin"
            with target.open("xb") as output:
                output.write(payload)
            target.chmod(0o600)
            return target.name

        await prepare_claimed_file_task(
            db_path=db_path, task_id=task_id,
            configured_download_dir=configured_download_dir,
            expected_bytes=len(payload), processor=processor,
            project_root=project_root, reserve_bytes=reserve_bytes,
        )
    except asyncio.CancelledError:
        with database(db_path) as db:
            cancel_job(db, task_id)
            change_status(db, task_id, "downloading", "failed")
        raise
    except Exception:
        logging.exception("Ошибка офлайн-задачи %d", task_id)
        with database(db_path) as db:
            cancel_job(db, task_id)
            change_status(db, task_id, "downloading", "failed")
    finally:
        if not finished:
            try:
                await asyncio.wait_for(
                    cancel_worker_reservation(socket_path, task_id, token),
                    timeout=3.5,
                )
            except (WorkerProtocolError, asyncio.TimeoutError, OSError):
                pass
    return task_id
