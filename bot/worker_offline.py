"""Fixed, network-free worker execution over authenticated Unix IPC.

Only a deterministic offline fixture is supported. Never execute media URLs.
"""
import asyncio
import base64
import tempfile
from pathlib import Path

from .offline_executor import execute_offline_job
from .worker_reservations import JobReservations, verify_running_lease


class OfflineJobController:
    def __init__(self, reservations: JobReservations):
        self.reservations = reservations
        self._cancel: asyncio.Event | None = None
        self._active_task: int | None = None
        self._lock = asyncio.Lock()

    def cancel(self, task_id: int, token: str) -> bool:
        if not self.reservations.owns(task_id, token):
            return False
        if self._active_task == task_id and self._cancel is not None:
            self._cancel.set()
        return self.reservations.cancel(task_id, token)

    async def execute(self, db_path: Path | None, task_id: int, token: str) -> dict:
        if self._lock.locked() or not self.reservations.owns(task_id, token):
            return {"version": 1, "status": "rejected", "downloads_enabled": False}
        async with self._lock:
            if not verify_running_lease(db_path, task_id, token):
                return {"version": 1, "status": "rejected", "downloads_enabled": False}
            self._active_task = task_id
            self._cancel = asyncio.Event()
            try:
                with tempfile.TemporaryDirectory(prefix="botdownload-offline-") as name:
                    workspace = Path(name)
                    result = await execute_offline_job(
                        workspace, timeout_seconds=10, cancel=self._cancel,
                    )
                    payload = result.read_bytes()
                if (self._cancel.is_set()
                        or not verify_running_lease(db_path, task_id, token)):
                    return {"version": 1, "status": "rejected", "downloads_enabled": False}
                return {
                    "version": 1, "status": "completed",
                    "downloads_enabled": False,
                    "filename": "offline-result.bin",
                    "data": base64.b64encode(payload).decode("ascii"),
                }
            except (Exception, asyncio.CancelledError):
                return {"version": 1, "status": "rejected", "downloads_enabled": False}
            finally:
                self._cancel = None
                self._active_task = None
                self.reservations.cancel(task_id, token)
