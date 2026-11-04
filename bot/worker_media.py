"""Authenticated media execution within the dedicated worker.

The broker remains the sole SQLite writer. This controller reads a running
lease, uses a private Unix CONNECT gateway, and returns a bounded file path.
"""
import asyncio
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
from urllib.parse import quote

from .media_egress_gateway import handle_connect
from .media_isolated_runner import execute_isolated
from .worker_reservations import verify_running_lease


def read_media_task(db_path: Path, task_id: int) -> tuple[str, str] | None:
    if not isinstance(db_path, Path) or not db_path.is_absolute():
        return None
    try:
        uri = "file:" + quote(str(db_path), safe="/") + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
            db.execute("PRAGMA query_only=ON")
            row = db.execute(
                "SELECT source_url,variant FROM tasks WHERE id=? AND status='downloading'",
                (task_id,),
            ).fetchone()
        return (row[0], row[1]) if row else None
    except (OSError, sqlite3.Error):
        return None


class MediaJobController:
    def __init__(self, reservations):
        self.reservations = reservations
        self._busy = False

    async def execute(self, db_path: Path, task_id: int, token: str) -> dict:
        rejected = {"version": 1, "status": "rejected", "downloads_enabled": False}
        if (self._busy or not self.reservations.owns(task_id, token)
                or not verify_running_lease(db_path, task_id, token)):
            return rejected
        task = read_media_task(db_path, task_id)
        if task is None:
            return rejected
        root_value = os.environ.get("BOTDOWNLOAD_MEDIA_ROOT", "")
        if not root_value:
            return rejected
        from .download_storage import download_root, create_task_directory, require_free_space
        try:
            root = download_root(root_value)
            require_free_space(root, 256 * 1024 * 1024)
        except (OSError, ValueError, Exception):
            return rejected
        self._busy = True
        workspace = None
        gateway = None
        gateway_dir = None
        try:
            workspace = create_task_directory(root, str(task_id))
            gateway_dir = tempfile.TemporaryDirectory(prefix="botdownload-egress-")
            gateway_path = Path(gateway_dir.name) / "gateway.sock"
            gateway = await asyncio.start_unix_server(handle_connect, path=str(gateway_path))
            os.chmod(gateway_path, 0o600)
            async with gateway:
                file = await execute_isolated(
                    task[0], gateway=gateway_path, workspace=workspace,
                    timeout_seconds=120, max_bytes=256 * 1024 * 1024,
                )
            # Socket is not a downloadable file; unlink before returning.
            if not verify_running_lease(db_path, task_id, token):
                return rejected
            st = file.lstat()
            if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
                    or st.st_nlink != 1 or not 0 < st.st_size <= 256 * 1024 * 1024):
                return rejected
            return {"version": 1, "status": "completed",
                    "downloads_enabled": True, "file": str(file)}
        except (OSError, ValueError, RuntimeError, TimeoutError):
            return rejected
        finally:
            if gateway is not None:
                gateway.close()
                await gateway.wait_closed()
            if gateway_dir is not None:
                gateway_dir.cleanup()
            self._busy = False
